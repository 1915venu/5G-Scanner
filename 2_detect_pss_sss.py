#!/usr/bin/env python3
"""
5G NR PSS/SSS Detector for Real Captured Signals
File: 2_detect_pss_sss.py

Description: Detects cells from USRP-captured 5G signals
Works with: 1_capture_5g.py output
Author: Your Name
Date: January 2026
"""

import numpy as np
import argparse
import json
from dataclasses import dataclass, asdict
from typing import List
from scipy import signal

# === CONFIGURATION ===
FFT_SIZE = 256
CP_LEN = 20
SAMPLE_RATE = 30.72e6
DETECTION_THRESHOLD_DB = 12.0  # Minimum SNR for valid detection

# === DATA STRUCTURES ===

@dataclass
class DetectedCell:
    """Container for detected cell information"""
    pci: int                # Physical Cell ID (0-1007)
    n_id_1: int            # SSS group ID (0-335)
    n_id_2: int            # PSS sector ID (0-2)
    timing_offset: int     # Sample index of PSS peak
    snr_db: float          # Detection SNR in dB
    rsrp_dbm: float        # Reference Signal Received Power
    cfo_estimate: float    # Normalized CFO estimate
    
    def __str__(self):
        return (f"PCI {self.pci:3d} (N_ID_1={self.n_id_1:3d}, N_ID_2={self.n_id_2}) | "
                f"Timing={self.timing_offset:8d} | SNR={self.snr_db:5.1f} dB | "
                f"RSRP={self.rsrp_dbm:6.1f} dBm | CFO={self.cfo_estimate:+.6f}")

# === PSS GENERATION (3GPP TS 38.211) ===

def generate_pss(n_id_2):
    """
    Generate Primary Synchronization Signal
    
    Args:
        n_id_2: Physical layer cell identity (0, 1, or 2)
    
    Returns:
        PSS sequence in frequency domain (127 values)
    """
    # Initialize m-sequence
    x = np.array([0, 1, 1, 0, 1, 1, 1])
    
    # Generate m-sequence: x(i+7) = (x(i+4) + x(i)) mod 2
    for i in range(120):
        next_val = (x[i+4] + x[i]) % 2
        x = np.append(x, next_val)
    
    # Generate PSS with BPSK mapping
    pss_seq = np.zeros(127)
    for n in range(127):
        idx = (n + 43 * n_id_2) % 127
        pss_seq[n] = 1 - 2 * x[idx]  # BPSK: 0→+1, 1→-1
    
    return pss_seq

def generate_pss_time_domain(n_id_2):
    """
    Generate time-domain PSS reference signal
    
    Args:
        n_id_2: PSS ID (0, 1, or 2)
    
    Returns:
        Time-domain PSS signal (FFT_SIZE samples)
    """
    # Generate frequency domain PSS
    pss_freq = generate_pss(n_id_2)
    
    # Map to OFDM subcarriers (center 127)
    subcarriers = np.zeros(FFT_SIZE, dtype=complex)
    center = FFT_SIZE // 2
    subcarriers[center-63:center+64] = pss_freq
    
    # IFFT to time domain
    pss_time = np.fft.ifft(np.fft.ifftshift(subcarriers)) * np.sqrt(FFT_SIZE)
    
    return pss_time

# === SSS GENERATION (3GPP TS 38.211) ===

def generate_sss(n_id_1, n_id_2):
    """
    Generate Secondary Synchronization Signal
    
    Args:
        n_id_1: Cell ID group (0-335)
        n_id_2: Cell ID sector (0-2)
    
    Returns:
        SSS sequence in frequency domain (127 values)
    """
    # Two m-sequences for SSS
    x0 = np.array([1, 0, 0, 0, 0, 0, 0])
    x1 = np.array([1, 0, 0, 0, 0, 0, 0])
    
    # Generate m-sequences
    for i in range(120):
        x0 = np.append(x0, (x0[i+4] + x0[i]) % 2)
        x1 = np.append(x1, (x1[i+1] + x1[i]) % 2)
    
    # Calculate indices
    m0 = 15 * (n_id_1 // 112) + (5 * n_id_2)
    m1 = n_id_1 % 112
    
    # Generate SSS sequence
    sss_seq = np.zeros(127)
    for n in range(127):
        d0 = 1 - 2 * x0[(n + m0) % 127]
        d1 = 1 - 2 * x1[(n + m1) % 127]
        sss_seq[n] = d0 * d1  # Correct: product of both m-sequences
    
    return sss_seq

# === PSS DETECTION ===

def detect_pss(rx_signal, threshold_db=DETECTION_THRESHOLD_DB):
    """
    Detect PSS in received signal
    
    Args:
        rx_signal: Received complex baseband signal
        threshold_db: Minimum SNR threshold in dB
    
    Returns:
        List of (n_id_2, timing, snr_db, peak_power) tuples
    """
    print("\n[*] Detecting PSS sequences...")
    print(f"    Signal length: {len(rx_signal)} samples")
    print(f"    SNR threshold: {threshold_db} dB")
    
    detections = []
    
    # Try all 3 PSS sequences
    for n_id_2 in range(3):
        # Generate reference
        pss_ref = generate_pss_time_domain(n_id_2)
        
        print(f"    Correlating with PSS[{n_id_2}]...", end='', flush=True)
        
        # FFT-based fast correlation (O(n log n) instead of O(n²))
        correlation = np.abs(signal.correlate(rx_signal, pss_ref, mode='valid'))
        
        # Find peaks
        peak_idx = np.argmax(correlation)
        peak_value = correlation[peak_idx]
        
        # Calculate noise floor (exclude peak region)
        noise_indices = np.ones(len(correlation), dtype=bool)
        noise_indices[max(0, peak_idx-1000):min(len(correlation), peak_idx+1000)] = False
        noise_avg = np.mean(correlation[noise_indices])
        
        # Calculate SNR
        snr_db = 20 * np.log10(peak_value / noise_avg) if noise_avg > 0 else 0
        
        print(f" Peak @ {peak_idx}, SNR = {snr_db:.1f} dB")
        
        if snr_db > threshold_db:
            detections.append((n_id_2, peak_idx, snr_db, peak_value))
    
    # Sort by SNR (strongest first)
    detections.sort(key=lambda x: x[2], reverse=True)
    
    return detections

# === SSS DETECTION ===

def detect_sss(rx_signal, pss_timing, n_id_2):
    """
    Detect SSS to get full cell ID
    
    Args:
        rx_signal: Received signal
        pss_timing: PSS detection timing offset
        n_id_2: Known PSS sector ID
    
    Returns:
        (n_id_1, correlation_strength) or (None, 0)
    """
    # SSS is 2 OFDM symbols after PSS
    symbol_len = FFT_SIZE + CP_LEN
    sss_start = pss_timing + 2 * symbol_len
    
    # Safety check
    if sss_start + FFT_SIZE > len(rx_signal):
        return None, 0
    
    # Extract SSS symbol
    sss_rx = rx_signal[sss_start:sss_start+FFT_SIZE]
    
    # FFT to frequency domain
    sss_rx_freq = np.fft.fftshift(np.fft.fft(sss_rx)) / np.sqrt(FFT_SIZE)
    
    # Extract center 127 subcarriers
    center = FFT_SIZE // 2
    sss_rx_127 = sss_rx_freq[center-63:center+64]
    
    # Try all possible N_ID_1 values
    best_n_id_1 = None
    best_corr = 0
    
    for n_id_1 in range(336):
        sss_ref = generate_sss(n_id_1, n_id_2)
        corr = np.abs(np.sum(sss_rx_127 * np.conj(sss_ref)))
        
        if corr > best_corr:
            best_corr = corr
            best_n_id_1 = n_id_1
    
    return best_n_id_1, best_corr

# === CFO ESTIMATION ===

def estimate_cfo(rx_signal, pss_timing):
    """
    Estimate carrier frequency offset using CP correlation
    
    Args:
        rx_signal: Received signal
        pss_timing: PSS timing offset
    
    Returns:
        Normalized CFO estimate
    """
    # Use CP correlation method
    cp_start = pss_timing - CP_LEN
    
    # Safety check
    if cp_start < 0 or cp_start + FFT_SIZE + CP_LEN >= len(rx_signal):
        return 0.0
    
    # Correlate CP with symbol tail
    cp_early = rx_signal[cp_start:cp_start+CP_LEN]
    cp_late = rx_signal[cp_start+FFT_SIZE:cp_start+FFT_SIZE+CP_LEN]
    
    # Complex correlation
    corr = np.sum(cp_late * np.conj(cp_early))
    
    # Extract phase and convert to CFO
    cfo = np.angle(corr) / (2 * np.pi)
    
    return cfo

# === RSRP CALCULATION ===

def calculate_rsrp(rx_signal, pss_timing, peak_power):
    """
    Calculate Reference Signal Received Power
    
    Args:
        rx_signal: Received signal
        pss_timing: PSS timing
        peak_power: PSS correlation peak
    
    Returns:
        RSRP in dBm (approximate)
    """
    # Extract PSS symbol
    if pss_timing + FFT_SIZE > len(rx_signal):
        return -120.0
    
    pss_symbol = rx_signal[pss_timing:pss_timing+FFT_SIZE]
    
    # Calculate power per RE
    power_per_re = np.mean(np.abs(pss_symbol)**2)
    
    # Convert to dBm (assuming 50 ohm, rough estimate)
    rsrp_dbm = 10 * np.log10(power_per_re) + 30
    
    return rsrp_dbm

# === MAIN DETECTION PIPELINE ===

def detect_cells(rx_signal):
    """
    Complete cell detection pipeline
    
    Args:
        rx_signal: Captured I/Q samples
    
    Returns:
        List of DetectedCell objects
    """
    print("\n" + "="*80)
    print("  5G NR CELL DETECTION PIPELINE")
    print("="*80)
    
    detected_cells = []
    
    # Step 1: PSS Detection
    pss_detections = detect_pss(rx_signal)
    
    if not pss_detections:
        print("\n[!] No PSS detected. Possible reasons:")
        print("    - No 5G signal at this frequency")
        print("    - Signal too weak (try increasing gain)")
        print("    - Wrong frequency band")
        return []
    
    print(f"\n[OK] Found {len(pss_detections)} PSS peak(s)")
    
    # Step 2: Process each detection
    for n_id_2, timing, snr_db, peak_power in pss_detections:
        print(f"\n--- Processing PSS[{n_id_2}] @ sample {timing} ---")
        
        # SSS Detection
        print(f"[*] Detecting SSS...")
        n_id_1, sss_corr = detect_sss(rx_signal, timing, n_id_2)
        
        if n_id_1 is None:
            print(f"[!] SSS detection failed (signal too short)")
            continue
        
        # Calculate PCI
        pci = 3 * n_id_1 + n_id_2
        print(f"[OK] N_ID_1 = {n_id_1}, N_ID_2 = {n_id_2}")
        print(f"[OK] Physical Cell ID = {pci}")
        
        # CFO Estimation
        cfo = estimate_cfo(rx_signal, timing)
        print(f"[*] CFO estimate: {cfo:+.6f}")
        
        # RSRP Calculation
        rsrp = calculate_rsrp(rx_signal, timing, peak_power)
        print(f"[*] RSRP: {rsrp:.1f} dBm (approximate)")
        
        # Create detection object
        cell = DetectedCell(
            pci=pci,
            n_id_1=n_id_1,
            n_id_2=n_id_2,
            timing_offset=timing,
            snr_db=snr_db,
            rsrp_dbm=rsrp,
            cfo_estimate=cfo
        )
        
        detected_cells.append(cell)
    
    return detected_cells

# === SAVE RESULTS ===

class NumpyEncoder(json.JSONEncoder):
    """Custom JSON encoder for numpy types"""
    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)

def save_results(cells, output_file):
    """Save detection results to JSON"""
    results = {
        'num_cells': len(cells),
        'cells': [asdict(cell) for cell in cells]
    }
    
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2, cls=NumpyEncoder)
    
    print(f"\n[OK] Results saved to: {output_file}")

# === MAIN ===

def main():
    parser = argparse.ArgumentParser(description='Detect 5G cells from captured signal')
    parser.add_argument('input', type=str, help='Input file from 1_capture_5g.py')
    parser.add_argument('-t', '--threshold', type=float, default=DETECTION_THRESHOLD_DB,
                       help=f'Detection threshold in dB (default: {DETECTION_THRESHOLD_DB})')
    parser.add_argument('-o', '--output', type=str, default='detection_results.json',
                       help='Output JSON file (default: detection_results.json)')
    
    args = parser.parse_args()
    
    # Load captured signal
    print(f"\n[*] Loading captured signal: {args.input}")
    try:
        rx_signal = np.fromfile(args.input, dtype=np.complex64)
        print(f"[OK] Loaded {len(rx_signal)} samples ({len(rx_signal)*8/1e6:.1f} MB)")
    except Exception as e:
        print(f"[ERROR] Failed to load file: {e}")
        return
    
    # Detect cells
    cells = detect_cells(rx_signal)
    
    # Print results
    print("\n" + "="*80)
    print("  DETECTION RESULTS")
    print("="*80)
    
    if cells:
        print(f"\nDetected {len(cells)} cell(s):\n")
        for i, cell in enumerate(cells, 1):
            print(f"{i}. {cell}")
        
        # Save to file
        save_results(cells, args.output)
        
        print(f"\nNext steps:")
        print(f"  1. Visualize: python 3_visualize_results.py {args.output}")
        print(f"  2. Compare with network info from your carrier")
    else:
        print("\n[!] No cells detected")
        print("\nTroubleshooting:")
        print("  1. Check if 5G is active in your area")
        print("  2. Try different frequencies: 3.4-3.8 GHz (n78)")
        print("  3. Increase RX gain: -g 50")
        print("  4. Move antenna to window/outside")
    
    print()

if __name__ == "__main__":
    main()
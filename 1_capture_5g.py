#!/usr/bin/env python3
"""
5G NR Signal Capture using USRP B210
File: 1_capture_5g.py

Description: Captures real 5G NR signals from cell towers
Hardware: USRP B210
Author: Your Name
Date: January 2026
"""

import uhd
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime
import argparse
import sys

# === CONFIGURATION ===
DEFAULT_FREQ = 3.5e9        # 3.5 GHz (n78 band - most common!)
DEFAULT_RATE = 30.72e6      # 30.72 MHz (5G NR standard rate)
DEFAULT_GAIN = 40           # Start with 40 dB
DEFAULT_DURATION = 5        # Capture 5 seconds
DEFAULT_OUTPUT = "5g_capture.dat"

# === USRP CONNECTION ===

def connect_usrp(sample_rate, center_freq, gain, clock_source="internal", time_source="internal"):
    """
    Initialize USRP B210 connection
    
    Args:
        sample_rate: Sampling rate in Hz
        center_freq: Center frequency in Hz
        gain: RX gain in dB
        clock_source: Clock reference source ("internal", "external", "gpsdo")
        time_source: Time reference source ("internal", "external", "gpsdo")
    
    Returns:
        usrp: USRP device object
        streamer: RX stream object
    """
    print("\n" + "="*60)
    print("  USRP B210 - 5G NR SIGNAL CAPTURE")
    print("="*60)
    
    try:
        # Find and connect to USRP
        print("[*] Searching for USRP B210...")
        usrp = uhd.usrp.MultiUSRP()
        
        # Get device info
        info = usrp.get_pp_string()
        print(f"[OK] Connected to: {info.split()[0]}")
        
        # Configure clock source BEFORE setting frequencies
        if clock_source != "internal":
            print(f"\n[*] Setting clock source: {clock_source}")
            usrp.set_clock_source(clock_source)
            print(f"[OK] Clock source: {clock_source}")
            
            # Wait for clock to lock (important for external references)
            import time
            print("[*] Waiting for clock to lock...", end='', flush=True)
            time.sleep(1.0)  # Give time for PLL to lock
            print(" Done")
        
        if time_source != "internal":
            print(f"[*] Setting time source: {time_source}")
            usrp.set_time_source(time_source)
            print(f"[OK] Time source: {time_source}")
        
        # Configure RX parameters
        print(f"\n[*] Configuring receiver...")
        usrp.set_rx_rate(sample_rate, 0)
        usrp.set_rx_freq(uhd.libpyuhd.types.tune_request(center_freq), 0)
        usrp.set_rx_gain(gain, 0)
        usrp.set_rx_bandwidth(sample_rate, 0)
        
        # Verify settings
        actual_rate = usrp.get_rx_rate(0)
        actual_freq = usrp.get_rx_freq(0)
        actual_gain = usrp.get_rx_gain(0)
        
        print(f"[OK] Sample Rate: {actual_rate/1e6:.2f} MHz")
        print(f"[OK] Center Freq: {actual_freq/1e9:.3f} GHz")
        print(f"[OK] RX Gain:     {actual_gain:.1f} dB")
        print(f"[OK] Clock Src:   {clock_source}")
        
        # Create RX streamer
        st_args = uhd.usrp.StreamArgs("fc32", "sc16")
        st_args.channels = [0]
        streamer = usrp.get_rx_stream(st_args)
        
        return usrp, streamer
        
    except RuntimeError as e:
        print(f"[ERROR] Failed to connect to USRP: {e}")
        print("\nTroubleshooting:")
        print("  1. Check USB connection")
        print("  2. Run: uhd_find_devices")
        print("  3. Update firmware: uhd_images_downloader")
        if clock_source == "external":
            print("  4. Check 10MHz reference is connected and powered")
        sys.exit(1)

# === SIGNAL CAPTURE ===

def capture_samples(streamer, num_samples):
    """
    Capture I/Q samples from USRP
    
    Args:
        streamer: USRP RX stream
        num_samples: Number of samples to capture
    
    Returns:
        samples: Complex numpy array
    """
    print(f"\n[*] Capturing {num_samples/1e6:.1f}M samples...")
    
    # Allocate buffer
    samples = np.zeros(num_samples, dtype=np.complex64)
    
    # Start streaming
    stream_cmd = uhd.types.StreamCMD(uhd.types.StreamMode.num_done)
    stream_cmd.num_samps = num_samples
    stream_cmd.stream_now = True
    streamer.issue_stream_cmd(stream_cmd)
    
    # Receive samples
    buffer = np.zeros((1, 10000), dtype=np.complex64)
    metadata = uhd.types.RXMetadata()
    
    total_received = 0
    timeout = 5.0  # 5 second timeout
    
    while total_received < num_samples:
        try:
            num_rx = streamer.recv(buffer, metadata, timeout)
            
            if metadata.error_code != uhd.types.RXMetadataErrorCode.none:
                print(f"[WARNING] RX error: {metadata.strerror()}")
                continue
            
            # Copy to output buffer
            end_idx = min(total_received + num_rx, num_samples)
            samples[total_received:end_idx] = buffer[0, :end_idx-total_received]
            total_received = end_idx
            
            # Progress indicator
            if total_received % 1000000 == 0:
                progress = (total_received / num_samples) * 100
                print(f"  Progress: {progress:.0f}%", end='\r')
                
        except RuntimeError as e:
            print(f"[ERROR] Receive failed: {e}")
            break
    
    print(f"  Progress: 100%  ")
    print(f"[OK] Captured {total_received} samples")
    
    return samples[:total_received]

# === QUICK ANALYSIS ===

def quick_analysis(samples, sample_rate, center_freq):
    """
    Perform quick signal analysis
    
    Args:
        samples: Captured I/Q samples
        sample_rate: Sample rate in Hz
        center_freq: Center frequency in Hz
    """
    print(f"\n[*] Quick Signal Analysis...")
    
    # Calculate power
    power_linear = np.mean(np.abs(samples)**2)
    power_dbm = 10 * np.log10(power_linear) + 30  # Assuming 50 ohm
    
    print(f"[*] Average Power: {power_dbm:.1f} dBm")
    
    # Calculate peak power
    peak_power = np.max(np.abs(samples)**2)
    peak_dbm = 10 * np.log10(peak_power) + 30
    
    print(f"[*] Peak Power:    {peak_dbm:.1f} dBm")
    
    # Calculate PAPR
    papr = peak_power / power_linear
    papr_db = 10 * np.log10(papr)
    
    print(f"[*] PAPR:          {papr_db:.1f} dB")
    
    # Detect if signal is present
    if power_dbm > -100:
        print(f"[OK] Signal detected! (Power > -100 dBm)")
    else:
        print(f"[WARNING] Weak signal (Power < -100 dBm)")
        print("         Try increasing gain or changing frequency")

# === VISUALIZATION ===

def plot_capture(samples, sample_rate, center_freq, save_path=None):
    """
    Create visualization of captured signal
    
    Args:
        samples: Captured I/Q samples
        sample_rate: Sample rate in Hz
        center_freq: Center frequency in Hz
        save_path: Optional path to save figure
    """
    print(f"\n[*] Generating plots...")
    
    fig, axes = plt.subplots(3, 1, figsize=(12, 10))
    
    # Plot 1: Time domain (first 1000 samples)
    time = np.arange(1000) / sample_rate * 1e3  # Convert to ms
    axes[0].plot(time, np.real(samples[:1000]), 'b-', alpha=0.7, label='I')
    axes[0].plot(time, np.imag(samples[:1000]), 'r-', alpha=0.7, label='Q')
    axes[0].set_xlabel('Time (ms)')
    axes[0].set_ylabel('Amplitude')
    axes[0].set_title('Time Domain (First 1000 samples)')
    axes[0].legend()
    axes[0].grid(True, alpha=0.3)
    
    # Plot 2: Power spectrum
    fft_size = 2048
    freqs = np.fft.fftshift(np.fft.fftfreq(fft_size, 1/sample_rate))
    spectrum = np.fft.fftshift(np.fft.fft(samples[:fft_size]))
    power_spectrum = 20 * np.log10(np.abs(spectrum) / fft_size)
    
    axes[1].plot(freqs/1e6, power_spectrum, 'b-', linewidth=0.5)
    axes[1].set_xlabel('Frequency Offset (MHz)')
    axes[1].set_ylabel('Power (dB)')
    axes[1].set_title(f'Power Spectrum @ {center_freq/1e9:.3f} GHz')
    axes[1].grid(True, alpha=0.3)
    axes[1].set_ylim([power_spectrum.max()-80, power_spectrum.max()+10])
    
    # Plot 3: Spectrogram (waterfall)
    num_ffts = min(512, len(samples) // 1024)
    axes[2].specgram(samples[:num_ffts*1024], NFFT=1024, Fs=sample_rate/1e6,
                     cmap='viridis', vmin=-80, vmax=-20)
    axes[2].set_xlabel('Time (s)')
    axes[2].set_ylabel('Frequency (MHz)')
    axes[2].set_title('Spectrogram (Waterfall)')
    
    plt.tight_layout()
    
    if save_path:
        plt.savefig(save_path, dpi=300, bbox_inches='tight')
        print(f"[OK] Plot saved to: {save_path}")
    
    print(f"[OK] Plots generated")
    print(f"[*] Close plot window to continue...")
    plt.show()

# === SAVE DATA ===

def save_samples(samples, filename, sample_rate, center_freq, gain):
    """
    Save samples to binary file with metadata
    
    Args:
        samples: I/Q samples
        filename: Output filename
        sample_rate: Sample rate
        center_freq: Center frequency
        gain: RX gain
    """
    print(f"\n[*] Saving to file...")
    
    # Save binary I/Q data
    samples.tofile(filename)
    
    # Save metadata
    meta_filename = filename.replace('.dat', '_meta.txt')
    with open(meta_filename, 'w') as f:
        f.write(f"Capture Time: {datetime.now()}\n")
        f.write(f"Sample Rate: {sample_rate} Hz ({sample_rate/1e6:.2f} MHz)\n")
        f.write(f"Center Freq: {center_freq} Hz ({center_freq/1e9:.3f} GHz)\n")
        f.write(f"RX Gain: {gain} dB\n")
        f.write(f"Num Samples: {len(samples)}\n")
        f.write(f"Duration: {len(samples)/sample_rate:.3f} seconds\n")
        f.write(f"File Size: {len(samples)*8/1e6:.1f} MB\n")
    
    print(f"[OK] Saved {len(samples)} samples ({len(samples)*8/1e6:.1f} MB)")
    print(f"[OK] Data file:     {filename}")
    print(f"[OK] Metadata file: {meta_filename}")

# === MAIN ===

def main():
    parser = argparse.ArgumentParser(description='Capture 5G NR signals with USRP B210')
    parser.add_argument('-f', '--freq', type=float, default=DEFAULT_FREQ,
                       help=f'Center frequency in Hz (default: {DEFAULT_FREQ/1e9}e9)')
    parser.add_argument('-r', '--rate', type=float, default=DEFAULT_RATE,
                       help=f'Sample rate in Hz (default: {DEFAULT_RATE/1e6}e6)')
    parser.add_argument('-g', '--gain', type=float, default=DEFAULT_GAIN,
                       help=f'RX gain in dB (default: {DEFAULT_GAIN})')
    parser.add_argument('-d', '--duration', type=float, default=DEFAULT_DURATION,
                       help=f'Capture duration in seconds (default: {DEFAULT_DURATION})')
    parser.add_argument('-o', '--output', type=str, default=DEFAULT_OUTPUT,
                       help=f'Output filename (default: {DEFAULT_OUTPUT})')
    parser.add_argument('--no-plot', action='store_true',
                       help='Skip plotting (headless mode)')
    parser.add_argument('--clock-source', type=str, default='internal',
                       choices=['internal', 'external', 'gpsdo'],
                       help='Clock reference source (default: internal)')
    parser.add_argument('--time-source', type=str, default='internal',
                       choices=['internal', 'external', 'gpsdo'],
                       help='Time reference source (default: internal)')
    
    args = parser.parse_args()
    
    # Calculate number of samples
    num_samples = int(args.rate * args.duration)
    
    # Connect to USRP
    usrp, streamer = connect_usrp(args.rate, args.freq, args.gain, 
                                   args.clock_source, args.time_source)
    
    # Capture samples
    samples = capture_samples(streamer, num_samples)
    
    # Quick analysis
    quick_analysis(samples, args.rate, args.freq)
    
    # Save to file
    save_samples(samples, args.output, args.rate, args.freq, args.gain)
    
    # Visualize (unless skipped)
    if not args.no_plot:
        plot_path = args.output.replace('.dat', '_spectrum.png')
        plot_capture(samples, args.rate, args.freq, plot_path)
    
    print("\n" + "="*60)
    print("  CAPTURE COMPLETE!")
    print("="*60)
    print(f"\nNext steps:")
    print(f"  1. Run detector: python 2_detect_pss_sss.py {args.output}")
    print(f"  2. View results: python 3_visualize_results.py")
    print()

if __name__ == "__main__":
    main()
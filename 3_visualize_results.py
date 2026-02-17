#!/usr/bin/env python3
"""
5G NR Detection Results Visualizer
File: 3_visualize_results.py

Description: Creates comprehensive visualization of detected cells
Author: Your Name
Date: January 2026
"""

import numpy as np
import matplotlib.pyplot as plt
import json
import argparse
from matplotlib.patches import Circle

# === LOAD RESULTS ===

def load_results(filename):
    """Load detection results from JSON"""
    with open(filename, 'r') as f:
        data = json.load(f)
    return data

# === VISUALIZATION ===

def create_summary_plot(results, capture_file=None):
    """
    Create comprehensive summary visualization
    
    Args:
        results: Detection results dictionary
        capture_file: Optional captured signal file for spectrum
    """
    cells = results['cells']
    num_cells = len(cells)
    
    if num_cells == 0:
        print("[!] No cells to visualize")
        return
    
    # Create figure
    fig = plt.figure(figsize=(16, 10))
    gs = fig.add_gridspec(3, 3, hspace=0.3, wspace=0.3)
    
    # ===== Plot 1: Cell ID Overview =====
    ax1 = fig.add_subplot(gs[0, :])
    
    pcis = [cell['pci'] for cell in cells]
    rsrps = [cell['rsrp_dbm'] for cell in cells]
    colors = plt.cm.viridis(np.linspace(0, 1, num_cells))
    
    bars = ax1.bar(range(num_cells), rsrps, color=colors, alpha=0.7, edgecolor='black')
    ax1.set_xlabel('Detected Cells', fontsize=12, fontweight='bold')
    ax1.set_ylabel('RSRP (dBm)', fontsize=12, fontweight='bold')
    ax1.set_title('Detected 5G NR Cells - Signal Strength', fontsize=14, fontweight='bold')
    ax1.set_xticks(range(num_cells))
    ax1.set_xticklabels([f'PCI {pci}' for pci in pcis])
    ax1.grid(True, alpha=0.3, axis='y')
    ax1.axhline(y=-100, color='red', linestyle='--', label='Typical minimum')
    ax1.legend()
    
    # Add value labels on bars
    for i, (bar, rsrp) in enumerate(zip(bars, rsrps)):
        height = bar.get_height()
        ax1.text(bar.get_x() + bar.get_width()/2., height + 1,
                f'{rsrp:.1f} dBm',
                ha='center', va='bottom', fontweight='bold')
    
    # ===== Plot 2: SNR Comparison =====
    ax2 = fig.add_subplot(gs[1, 0])
    
    snrs = [cell['snr_db'] for cell in cells]
    ax2.barh(range(num_cells), snrs, color=colors, alpha=0.7, edgecolor='black')
    ax2.set_yticks(range(num_cells))
    ax2.set_yticklabels([f'PCI {pci}' for pci in pcis])
    ax2.set_xlabel('SNR (dB)', fontsize=11, fontweight='bold')
    ax2.set_title('Detection SNR', fontsize=12, fontweight='bold')
    ax2.grid(True, alpha=0.3, axis='x')
    ax2.axvline(x=12, color='orange', linestyle='--', label='Detection threshold')
    ax2.legend()
    
    # ===== Plot 3: CFO Estimates =====
    ax3 = fig.add_subplot(gs[1, 1])
    
    cfos = [cell['cfo_estimate'] for cell in cells]
    ax3.scatter(range(num_cells), cfos, c=colors, s=200, alpha=0.7, edgecolor='black')
    ax3.set_xticks(range(num_cells))
    ax3.set_xticklabels([f'PCI {pci}' for pci in pcis])
    ax3.set_ylabel('Normalized CFO', fontsize=11, fontweight='bold')
    ax3.set_title('Carrier Frequency Offset', fontsize=12, fontweight='bold')
    ax3.grid(True, alpha=0.3)
    ax3.axhline(y=0, color='black', linestyle='-', linewidth=0.5)
    
    # ===== Plot 4: Timing Offsets =====
    ax4 = fig.add_subplot(gs[1, 2])
    
    timings = [cell['timing_offset'] for cell in cells]
    ax4.scatter(range(num_cells), timings, c=colors, s=200, alpha=0.7, edgecolor='black')
    ax4.set_xticks(range(num_cells))
    ax4.set_xticklabels([f'PCI {pci}' for pci in pcis])
    ax4.set_ylabel('Timing Offset (samples)', fontsize=11, fontweight='bold')
    ax4.set_title('PSS Detection Timing', fontsize=12, fontweight='bold')
    ax4.grid(True, alpha=0.3)
    ax4.ticklabel_format(style='plain', axis='y')
    
    # ===== Plot 5: Cell ID Breakdown =====
    ax5 = fig.add_subplot(gs[2, 0])
    
    n_id_2_counts = [0, 0, 0]
    for cell in cells:
        n_id_2_counts[cell['n_id_2']] += 1
    
    ax5.pie(n_id_2_counts, labels=['N_ID_2=0', 'N_ID_2=1', 'N_ID_2=2'],
            autopct='%1.0f%%', startangle=90, colors=['#ff9999', '#66b3ff', '#99ff99'])
    ax5.set_title('PSS Sector Distribution', fontsize=12, fontweight='bold')
    
    # ===== Plot 6: Cell Details Table =====
    ax6 = fig.add_subplot(gs[2, 1:])
    ax6.axis('off')
    
    # Create table data
    table_data = []
    headers = ['PCI', 'N_ID_1', 'N_ID_2', 'SNR (dB)', 'RSRP (dBm)', 'CFO', 'Timing']
    
    for cell in cells:
        row = [
            f"{cell['pci']}",
            f"{cell['n_id_1']}",
            f"{cell['n_id_2']}",
            f"{cell['snr_db']:.1f}",
            f"{cell['rsrp_dbm']:.1f}",
            f"{cell['cfo_estimate']:+.4f}",
            f"{cell['timing_offset']}"
        ]
        table_data.append(row)
    
    table = ax6.table(cellText=table_data, colLabels=headers,
                      cellLoc='center', loc='center',
                      colColours=['lightgray']*len(headers))
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1, 2)
    
    ax6.set_title('Detailed Cell Information', fontsize=12, fontweight='bold', pad=20)
    
    # ===== Optional: Spectrum Plot =====
    if capture_file:
        try:
            print(f"[*] Loading capture file for spectrum: {capture_file}")
            rx_signal = np.fromfile(capture_file, dtype=np.complex64)
            
            # Add spectrum to top right if space
            # (Could be enhanced based on layout needs)
            print(f"[OK] Loaded {len(rx_signal)} samples")
        except:
            pass
    
    plt.suptitle('5G NR Cell Detection - Complete Analysis', 
                 fontsize=16, fontweight='bold', y=0.98)
    
    plt.savefig('detection_summary.png', dpi=300, bbox_inches='tight')
    print("[OK] Saved: detection_summary.png")
    
    plt.show()

# === DETAILED REPORT ===

def print_detailed_report(results):
    """Print detailed text report"""
    cells = results['cells']
    
    print("\n" + "="*80)
    print("  5G NR CELL DETECTION - DETAILED REPORT")
    print("="*80)
    
    print(f"\nTotal Cells Detected: {len(cells)}")
    
    if len(cells) == 0:
        return
    
    # Sort by RSRP (strongest first)
    cells_sorted = sorted(cells, key=lambda x: x['rsrp_dbm'], reverse=True)
    
    print("\n" + "-"*80)
    print("CELLS RANKED BY SIGNAL STRENGTH:")
    print("-"*80)
    
    for i, cell in enumerate(cells_sorted, 1):
        print(f"\n{i}. Physical Cell ID: {cell['pci']} (N_ID_1={cell['n_id_1']}, N_ID_2={cell['n_id_2']})")
        print(f"   Signal Strength:")
        print(f"     - RSRP:          {cell['rsrp_dbm']:.1f} dBm")
        print(f"     - Detection SNR: {cell['snr_db']:.1f} dB")
        
        # Signal quality assessment
        if cell['rsrp_dbm'] > -80:
            quality = "EXCELLENT"
        elif cell['rsrp_dbm'] > -90:
            quality = "GOOD"
        elif cell['rsrp_dbm'] > -100:
            quality = "FAIR"
        else:
            quality = "WEAK"
        print(f"     - Quality:       {quality}")
        
        print(f"   Synchronization:")
        print(f"     - Timing Offset: {cell['timing_offset']} samples")
        print(f"     - CFO Estimate:  {cell['cfo_estimate']:+.6f} (normalized)")
        print(f"     - CFO in Hz:     {cell['cfo_estimate'] * 15000:+.1f} Hz (approx, SCS=15kHz)")
    
    # Summary statistics
    print("\n" + "-"*80)
    print("SUMMARY STATISTICS:")
    print("-"*80)
    
    avg_rsrp = np.mean([c['rsrp_dbm'] for c in cells])
    avg_snr = np.mean([c['snr_db'] for c in cells])
    max_rsrp = max([c['rsrp_dbm'] for c in cells])
    min_rsrp = min([c['rsrp_dbm'] for c in cells])
    
    print(f"  Average RSRP:      {avg_rsrp:.1f} dBm")
    print(f"  Average SNR:       {avg_snr:.1f} dB")
    print(f"  RSRP Range:        {min_rsrp:.1f} to {max_rsrp:.1f} dBm")
    print(f"  Signal Spread:     {max_rsrp - min_rsrp:.1f} dB")
    
    # Strongest cell recommendation
    strongest = cells_sorted[0]
    print(f"\n  Recommended Cell:  PCI {strongest['pci']} ({strongest['rsrp_dbm']:.1f} dBm)")
    
    print("\n" + "="*80)

# === EXPORT TO CSV ===

def export_to_csv(results, filename='detection_results.csv'):
    """Export results to CSV file"""
    import csv
    
    cells = results['cells']
    
    if len(cells) == 0:
        print("[!] No cells to export")
        return
    
    with open(filename, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=cells[0].keys())
        writer.writeheader()
        writer.writerows(cells)
    
    print(f"[OK] Exported to CSV: {filename}")

# === MAIN ===

def main():
    parser = argparse.ArgumentParser(description='Visualize 5G cell detection results')
    parser.add_argument('input', type=str, help='Input JSON file from 2_detect_pss_sss.py')
    parser.add_argument('-c', '--capture', type=str, default=None,
                       help='Original capture file for spectrum plot')
    parser.add_argument('--csv', action='store_true',
                       help='Export to CSV')
    parser.add_argument('--no-plot', action='store_true',
                       help='Skip plotting (text report only)')
    
    args = parser.parse_args()
    
    # Load results
    print(f"[*] Loading results: {args.input}")
    try:
        results = load_results(args.input)
        print(f"[OK] Loaded results for {results['num_cells']} cell(s)")
    except Exception as e:
        print(f"[ERROR] Failed to load results: {e}")
        return
    
    # Print detailed report
    print_detailed_report(results)
    
    # Export to CSV if requested
    if args.csv:
        export_to_csv(results)
    
    # Create visualizations
    if not args.no_plot and results['num_cells'] > 0:
        create_summary_plot(results, args.capture)
    
    print("\n[OK] Analysis complete!")

if __name__ == "__main__":
    main()
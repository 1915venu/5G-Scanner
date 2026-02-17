# 5G NR Cell Scanner - Complete Study Notes 📚

## Table of Contents
1. [Big Picture Overview](#1-big-picture-overview)
2. [File 1: Signal Capture](#2-file-1-signal-capture)
3. [File 2: PSS/SSS Detection (Core Logic)](#3-file-2-psssss-detection)
4. [File 3: Visualization](#4-file-3-visualization)
5. [Key Formulas & Concepts](#5-key-formulas--concepts)
6. [Quick Reference Card](#6-quick-reference-card)

---

## 1. Big Picture Overview

### What Does This Project Do?

```
┌─────────────┐    ┌──────────────┐    ┌─────────────┐
│  5G Cell    │    │   USRP B210  │    │   Python    │
│   Tower     │───▶│    (SDR)     │───▶│   Scripts   │
│  (3.5 GHz)  │    │  I/Q Samples │    │  Detection  │
└─────────────┘    └──────────────┘    └─────────────┘
                          │                   │
                          ▼                   ▼
                   5g_capture.dat       PCI 215, 154, 201
                   (1.2 GB raw data)    (Cell IDs found!)
```

### The 3 Scripts Pipeline

| Script | Input | Output | Purpose |
|--------|-------|--------|---------|
| `1_capture_5g.py` | RF signals | `.dat` file | Capture raw I/Q samples |
| `2_detect_pss_sss.py` | `.dat` file | `.json` results | Find cell IDs |
| `3_visualize_results.py` | `.json` | Charts + report | Display results |

---

## 2. File 1: Signal Capture (1_capture_5g.py)

### Configuration Parameters (Lines 19-24)
```python
DEFAULT_FREQ = 3.5e9        # 3.5 GHz - n78 band (5G mid-band)
DEFAULT_RATE = 30.72e6      # Standard 5G NR sample rate
DEFAULT_GAIN = 40           # RF amplifier gain in dB
DEFAULT_DURATION = 5        # Seconds to capture
```

**Why 30.72 MHz?**
```
Sample Rate = FFT_size × Subcarrier_Spacing
30.72 MHz = 2048 × 15 kHz
```
This is the standard rate for 5G NR with 15 kHz subcarrier spacing (μ=0).

### connect_usrp() Function (Lines 28-105)

**Purpose:** Initialize SDR hardware and configure receiver.

**Key Steps:**
1. Find USRP device: `usrp = uhd.usrp.MultiUSRP()`
2. Set clock source (internal/external/GPSDO)
3. Configure RX: rate, frequency, gain, bandwidth
4. Create streamer for I/Q data

**Important Code:**
```python
# Set receiver parameters
usrp.set_rx_rate(sample_rate, 0)      # Channel 0
usrp.set_rx_freq(center_freq, 0)       # Tune to 3.5 GHz
usrp.set_rx_gain(gain, 0)              # 40 dB gain
usrp.set_rx_bandwidth(sample_rate, 0)  # Match BW to sample rate

# Create data streamer
st_args = uhd.usrp.StreamArgs("fc32", "sc16")  # Float complex out, 16-bit in
streamer = usrp.get_rx_stream(st_args)
```

### capture_samples() Function (Lines 109-163)

**Purpose:** Receive I/Q samples from SDR.

**Key Concepts:**
- **I/Q samples**: Complex numbers representing amplitude & phase
- **Streaming**: Continuous data flow from hardware
- **Buffer**: Temporary storage for received chunks

```python
# Allocate output buffer
samples = np.zeros(num_samples, dtype=np.complex64)

# Start streaming command
stream_cmd = uhd.types.StreamCMD(uhd.types.StreamMode.num_done)
stream_cmd.num_samps = num_samples  # How many samples to capture
streamer.issue_stream_cmd(stream_cmd)

# Receive loop
while total_received < num_samples:
    num_rx = streamer.recv(buffer, metadata, timeout)
    samples[total_received:...] = buffer[0, :num_rx]
```

### quick_analysis() Function (Lines 167-201)

**Calculates:**
- **Average Power**: `10 * log10(mean(|samples|²)) + 30` → dBm
- **Peak Power**: Maximum instantaneous power
- **PAPR**: Peak-to-Average Power Ratio (typical: 8-12 dB for OFDM)

---

## 3. File 2: PSS/SSS Detection (2_detect_pss_sss.py)

### ⭐ THIS IS THE CORE FILE - Study This Carefully!

### Configuration (Lines 20-23)
```python
FFT_SIZE = 256              # Smaller FFT for detection (not full 2048)
CP_LEN = 20                 # Cyclic prefix length
SAMPLE_RATE = 30.72e6       # Must match capture
DETECTION_THRESHOLD_DB = 12.0  # Minimum SNR to accept detection
```

---

### 🔴 PSS Generation (Lines 45-92)

#### What is PSS?
**Primary Synchronization Signal** - First thing UE searches for.
- Enables timing synchronization
- Identifies sector: N_ID_2 = 0, 1, or 2
- Only 3 possible sequences!

#### The Math: M-Sequence Generation

**Generator Polynomial:** x⁷ + x⁴ + 1

```python
def generate_pss(n_id_2):
    # Initial state: [0, 1, 1, 0, 1, 1, 1] (x(0) to x(6))
    x = np.array([0, 1, 1, 0, 1, 1, 1])
    
    # Generate 127 values using recurrence relation
    for i in range(120):
        # x(i+7) = x(i+4) XOR x(i)
        next_val = (x[i+4] + x[i]) % 2
        x = np.append(x, next_val)
    
    # Apply cyclic shift based on n_id_2
    pss_seq = np.zeros(127)
    for n in range(127):
        idx = (n + 43 * n_id_2) % 127  # Shift by 0, 43, or 86
        pss_seq[n] = 1 - 2 * x[idx]    # BPSK: 0→+1, 1→-1
    
    return pss_seq
```

**Key Points:**
- M-sequence length: 127 (= 2⁷ - 1)
- Cyclic shift of 43 between each N_ID_2
- BPSK mapping: bit 0 → +1, bit 1 → -1

#### Time Domain PSS (Lines 71-92)

```python
def generate_pss_time_domain(n_id_2):
    pss_freq = generate_pss(n_id_2)  # 127 frequency samples
    
    # Map to center of FFT
    subcarriers = np.zeros(FFT_SIZE, dtype=complex)
    center = FFT_SIZE // 2
    subcarriers[center-63:center+64] = pss_freq  # 127 subcarriers
    
    # IFFT to get time domain
    pss_time = np.fft.ifft(np.fft.ifftshift(subcarriers)) * np.sqrt(FFT_SIZE)
    
    return pss_time
```

**Why ifftshift?** Moves DC (center) to position 0 for correct IFFT.

---

### 🔵 SSS Generation (Lines 96-127)

#### What is SSS?
**Secondary Synchronization Signal** - Provides cell ID group.
- N_ID_1 = 0 to 335 (336 possible values)
- Combined with PSS: **PCI = 3 × N_ID_1 + N_ID_2**
- Total: 1008 possible PCIs

#### The Math: Two M-Sequences

```python
def generate_sss(n_id_1, n_id_2):
    # Two different m-sequences
    x0 = np.array([1, 0, 0, 0, 0, 0, 0])  # Generator: x^7 + x^4 + 1
    x1 = np.array([1, 0, 0, 0, 0, 0, 0])  # Generator: x^7 + x + 1
    
    # Generate sequences
    for i in range(120):
        x0 = np.append(x0, (x0[i+4] + x0[i]) % 2)  # Same as PSS
        x1 = np.append(x1, (x1[i+1] + x1[i]) % 2)  # Different!
    
    # Calculate indices that encode the cell ID
    m0 = 15 * (n_id_1 // 112) + (5 * n_id_2)  # 0-167
    m1 = n_id_1 % 112                          # 0-111
    
    # Generate SSS
    for n in range(127):
        d0 = 1 - 2 * x0[(n + m0) % 127]
        d1 = 1 - 2 * x1[(n + m1) % 127]
        sss_seq[n] = d0 * d1  # Product of both sequences
    
    return sss_seq
```

**Key Insight:** The indices m0 and m1 encode N_ID_1 and N_ID_2!

---

### 🟢 PSS Detection (Lines 131-178)

#### Algorithm: Cross-Correlation

```python
def detect_pss(rx_signal, threshold_db):
    detections = []
    
    for n_id_2 in range(3):  # Try all 3 PSS sequences
        pss_ref = generate_pss_time_domain(n_id_2)
        
        # FFT-based correlation (fast!)
        correlation = np.abs(signal.correlate(rx_signal, pss_ref, mode='valid'))
        
        # Find peak
        peak_idx = np.argmax(correlation)
        peak_value = correlation[peak_idx]
        
        # Calculate noise floor (exclude peak region)
        noise_indices = np.ones(len(correlation), dtype=bool)
        noise_indices[peak_idx-1000:peak_idx+1000] = False
        noise_avg = np.mean(correlation[noise_indices])
        
        # SNR calculation
        snr_db = 20 * np.log10(peak_value / noise_avg)
        
        if snr_db > threshold_db:
            detections.append((n_id_2, peak_idx, snr_db, peak_value))
    
    return detections
```

**Why Correlation Works:**
```
M-sequence autocorrelation:
  R(0)   = N = 127  (peak at correct timing)
  R(τ≠0) = -1       (flat elsewhere)
  
Peak-to-sidelobe ratio ≈ 10*log10(127) ≈ 21 dB
```

---

### 🟡 SSS Detection (Lines 182-224)

```python
def detect_sss(rx_signal, pss_timing, n_id_2):
    # SSS is 2 OFDM symbols after PSS
    symbol_len = FFT_SIZE + CP_LEN
    sss_start = pss_timing + 2 * symbol_len
    
    # Extract and FFT
    sss_rx = rx_signal[sss_start:sss_start+FFT_SIZE]
    sss_rx_freq = np.fft.fftshift(np.fft.fft(sss_rx)) / np.sqrt(FFT_SIZE)
    
    # Extract center 127 subcarriers
    center = FFT_SIZE // 2
    sss_rx_127 = sss_rx_freq[center-63:center+64]
    
    # Try all 336 possible N_ID_1 values
    best_n_id_1 = None
    best_corr = 0
    
    for n_id_1 in range(336):
        sss_ref = generate_sss(n_id_1, n_id_2)
        corr = np.abs(np.sum(sss_rx_127 * np.conj(sss_ref)))
        
        if corr > best_corr:
            best_corr = corr
            best_n_id_1 = n_id_1
    
    return best_n_id_1, best_corr
```

---

### 🟣 CFO Estimation (Lines 228-256)

**CFO = Carrier Frequency Offset** - Mismatch between TX and RX oscillators.

#### CP Correlation Method

```python
def estimate_cfo(rx_signal, pss_timing):
    cp_start = pss_timing - CP_LEN
    
    # CP is copy of symbol tail
    cp_early = rx_signal[cp_start:cp_start+CP_LEN]
    cp_late = rx_signal[cp_start+FFT_SIZE:cp_start+FFT_SIZE+CP_LEN]
    
    # Complex correlation
    corr = np.sum(cp_late * np.conj(cp_early))
    
    # Phase = CFO × 2π × symbol_duration
    cfo = np.angle(corr) / (2 * np.pi)
    
    return cfo  # Normalized CFO
```

**Why This Works:**
```
OFDM Symbol: [CP][.....DATA.....]
              └──── Same as ────┘
              
If CFO exists: phase rotates by φ = 2π × f_offset × T_symbol
Extract φ from correlation angle → recover f_offset
```

---

## 4. File 3: Visualization (3_visualize_results.py)

Creates matplotlib plots:
- RSRP bar chart (signal strength)
- SNR comparison
- CFO scatter plot
- Timing offsets
- N_ID_2 distribution pie chart
- Detailed table

---

## 5. Key Formulas & Concepts

### Physical Cell ID
```
PCI = 3 × N_ID_1 + N_ID_2

Where:
  N_ID_1 = 0 to 335 (from SSS)
  N_ID_2 = 0 to 2   (from PSS)
  PCI    = 0 to 1007
```

### Sample Rate Formula
```
Sample_Rate = FFT_size × Subcarrier_Spacing

5G NR μ=0: 30.72 MHz = 2048 × 15 kHz
5G NR μ=1: 61.44 MHz = 2048 × 30 kHz
```

### RSRP Calculation
```
RSRP = 10 × log10(Power_per_RE) + 30 [dBm]
```

### SNR Calculation
```
SNR_dB = 20 × log10(Peak / Noise_floor)
```

### CFO in Hz
```
CFO_Hz = Normalized_CFO × Subcarrier_Spacing
       = cfo_estimate × 15000 Hz
```

---

## 6. Quick Reference Card

### M-Sequence Properties
| Property | Value |
|----------|-------|
| Length | 2^n - 1 (127 for PSS/SSS) |
| Autocorr peak | N |
| Autocorr off-peak | -1 |
| Generator (PSS) | x⁷ + x⁴ + 1 |

### Detection Hierarchy
```
1. PSS Detection → Get N_ID_2 (0, 1, or 2) + Timing
2. SSS Detection → Get N_ID_1 (0 to 335)
3. Calculate PCI = 3 × N_ID_1 + N_ID_2
```

### Signal Quality Thresholds
| RSRP (dBm) | Quality |
|------------|---------|
| > -80 | EXCELLENT |
| -80 to -90 | GOOD |
| -90 to -100 | FAIR |
| < -100 | WEAK |

### 5G NR Frequency Bands
| Band | Frequency | Common Use |
|------|-----------|------------|
| n78 | 3.3-3.8 GHz | Mid-band 5G (most common) |
| n77 | 3.3-4.2 GHz | C-band |
| n79 | 4.4-5.0 GHz | High capacity |

---

## Study Tips 💡

1. **Start with PSS** - It's simpler (only 3 sequences)
2. **Understand m-sequences** - Key to both PSS and SSS
3. **Draw the timing diagram** - Where is PSS vs SSS in the frame?
4. **Trace the correlation** - Why does the peak appear?
5. **Run the code step by step** - Add print statements!

### Practice Questions
1. Why are there exactly 1008 PCIs?
2. What happens if CFO is not corrected?
3. Why use cyclic prefix for CFO estimation?
4. How would detection fail in low SNR?

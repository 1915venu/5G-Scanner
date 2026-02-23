# 5G NR Cell Scanner — Code + Concepts: A Continuous Walkthrough

>

---

## THE BIG PICTURE: What Are We Building?

A **passive 5G cell scanner**. It has three scripts that run as a pipeline:

```
1_capture_5g.py  →  5g_capture.dat  →  2_detect_pss_sss.py  →  detection_results.json  →  3_visualize_results.py
     (SDR HW)         (raw I/Q)           (DSP + 3GPP)             (cell IDs)                (plots + reports)
```

**Real-world analogy:** Think of it like a radio scanner. You tune to a frequency, record everything you hear, then analyze the recording to figure out which cell towers are transmitting.

---

# SCRIPT 1: `1_capture_5g.py` — Signal Capture

This script talks to the **USRP B210** (Software Defined Radio hardware) and records raw radio signals from the air.

---

## Step 1.1: Configuration Constants (Lines 19-24)

```python
DEFAULT_FREQ = 3.5e9        # 3.5 GHz (n78 band)
DEFAULT_RATE = 30.72e6      # 30.72 MHz sample rate
DEFAULT_GAIN = 40           # 40 dB receiver amplification
DEFAULT_DURATION = 5        # 5 seconds of capture
```

### 💡 Concept: Why these specific numbers?

**3.5 GHz (n78 band):** This is the most widely deployed 5G NR mid-band frequency worldwide. In India, Jio and Airtel both use this band. It's the sweet spot — not too high frequency (which would have poor range like mmWave) and not too low (which would have limited bandwidth like sub-1 GHz).

**30.72 MHz sample rate — where does this magic number come from?**

In 5G NR, the OFDM system is built on a specific relationship:

```
Sample Rate = FFT Size × Subcarrier Spacing
```

For the standard numerology μ=0:
- FFT Size = 2048 points
- Subcarrier Spacing (SCS) = 15 kHz
- **Sample Rate = 2048 × 15,000 = 30,720,000 Hz = 30.72 MHz**

This is not arbitrary — it's mandated by the 3GPP standard so that each FFT bin corresponds to exactly one subcarrier. If you sample at any other rate, the FFT bins won't align with the subcarriers, and you'll get **inter-carrier interference (ICI)**.

**40 dB gain:** The received signal from a cell tower at typical indoor distances is extremely weak (around -80 to -100 dBm). The gain amplifies it to a level the ADC can digitize. Too low → signal buried in noise. Too high → ADC saturates (clips).

---

## Step 1.2: Connecting to the USRP — `connect_usrp()` (Lines 28-105)

```python
usrp = uhd.usrp.MultiUSRP()

usrp.set_rx_rate(sample_rate, 0)      # Set sampling rate on channel 0
usrp.set_rx_freq(uhd.libpyuhd.types.tune_request(center_freq), 0)  # Tune to 3.5 GHz
usrp.set_rx_gain(gain, 0)             # Set amplifier gain
usrp.set_rx_bandwidth(sample_rate, 0) # Set analog filter bandwidth

st_args = uhd.usrp.StreamArgs("fc32", "sc16")  # Output: float complex, Hardware: 16-bit int
streamer = usrp.get_rx_stream(st_args)
```

### 💡 Concept: I/Q Sampling and Complex Baseband

**What is I/Q?** When the USRP captures a radio signal, it doesn't just record voltage vs time like a microphone. It captures **two signals simultaneously**:
- **I (In-phase):** The component aligned with a reference cosine wave
- **Q (Quadrature):** The component aligned with a reference sine wave (90° shifted)

Together, I + jQ forms a **complex number** at each time instant:

```
sample[n] = I[n] + j·Q[n]
```

**Why complex?** Because a real signal at 3.5 GHz oscillates billions of times per second — you can't digitize that directly. Instead, the USRP multiplies the signal by a local oscillator at 3.5 GHz (called **downconversion**), which shifts everything down to near 0 Hz (**baseband**). The complex representation preserves both amplitude AND phase information lost in real-valued downconversion.

**`"fc32"` vs `"sc16"`:** The hardware ADC produces 16-bit integer samples (`sc16`). The UHD driver converts these to 32-bit floating-point complex (`fc32`) for easier math in Python. Each sample = 4 bytes (I) + 4 bytes (Q) = 8 bytes.

**`set_rx_bandwidth`:** This controls the analog anti-aliasing filter. By Nyquist's theorem, you can only capture signals up to `sample_rate/2 = 15.36 MHz` on either side of center. The bandwidth filter rejects signals beyond this to prevent **aliasing** (signals folding back into your captured band).

---

## Step 1.3: Capturing Samples — `capture_samples()` (Lines 109-163)

```python
samples = np.zeros(num_samples, dtype=np.complex64)  # Pre-allocate buffer

stream_cmd = uhd.types.StreamCMD(uhd.types.StreamMode.num_done)
stream_cmd.num_samps = num_samples   # Capture exactly this many
stream_cmd.stream_now = True          # Start immediately
streamer.issue_stream_cmd(stream_cmd)

buffer = np.zeros((1, 10000), dtype=np.complex64)  # Small receive buffer
while total_received < num_samples:
    num_rx = streamer.recv(buffer, metadata, timeout)  # Receive a chunk
    samples[total_received:end_idx] = buffer[0, :end_idx-total_received]
    total_received = end_idx
```

### 💡 Concept: Streaming I/Q Data

The USRP sends data in **chunks** (typically 10,000 samples at a time) over USB 3.0. We accumulate these chunks into one big array.

**How much data?**
```
5 seconds × 30.72 MHz = 153,600,000 samples
× 8 bytes/sample = 1,228,800,000 bytes ≈ 1.2 GB
```

That's why the capture file `5g_capture.dat` is 1.2 GB — it's 153.6 million complex samples, each stored as two 32-bit floats.

**`complex64` dtype:** NumPy's `complex64` means each complex number uses 64 bits total = 32 bits for the real part (I) + 32 bits for the imaginary part (Q).

---

## Step 1.4: Quick Signal Analysis — `quick_analysis()` (Lines 167-201)

```python
power_linear = np.mean(np.abs(samples)**2)          # Average power
power_dbm = 10 * np.log10(power_linear) + 30        # Convert to dBm

peak_power = np.max(np.abs(samples)**2)              # Peak power
papr = peak_power / power_linear                     # Peak to Average
papr_db = 10 * np.log10(papr)
```

### 💡 Concept: Power Measurements and PAPR

**`np.abs(samples)**2`:** For a complex sample `s = I + jQ`, the instantaneous power is `|s|² = I² + Q²`. This is the squared magnitude.

**dBm conversion:** dBm means "decibels relative to 1 milliwatt".
```
Power_dBm = 10 × log10(Power_watts) + 30
```
The `+30` converts watts to milliwatts (since 1W = 1000mW = 10^3 mW, and 10×log10(1000) = 30).

**PAPR (Peak-to-Average Power Ratio):** OFDM signals have high PAPR (typically 8-12 dB) because many subcarriers can constructively add up at certain time instants, creating brief power spikes. This is important because the power amplifier must handle these peaks without distortion. Seeing a PAPR of ~10 dB is actually a good sign that you're receiving a real OFDM signal.

**Signal detection heuristic:** If average power > -100 dBm, there's likely a real signal present. Below that, it's probably just the noise floor of the receiver.

---

## Step 1.5: Spectrum Visualization — `plot_capture()` (Lines 205-258)

```python
fft_size = 2048
freqs = np.fft.fftshift(np.fft.fftfreq(fft_size, 1/sample_rate))
spectrum = np.fft.fftshift(np.fft.fft(samples[:fft_size]))
power_spectrum = 20 * np.log10(np.abs(spectrum) / fft_size)
```

### 💡 Concept: From Time Domain to Frequency Domain

**`np.fft.fft()`:** Takes 2048 time-domain samples and transforms them into 2048 frequency-domain bins. Each bin represents the signal energy at a specific frequency.

**`np.fft.fftfreq()`:** Generates the frequency labels for each bin. With sample rate 30.72 MHz and 2048 bins, each bin is 30.72e6/2048 = 15 kHz wide — exactly one subcarrier spacing!

**`np.fft.fftshift()`:** By default, FFT output has DC (0 Hz) at index 0, positive frequencies in the first half, and negative frequencies in the second half. `fftshift` rearranges them so DC is in the center — which is how we naturally think of a spectrum.

**`20 * np.log10(...)`:** We use 20× (not 10×) because we're converting amplitude (not power) to dB. Since power ∝ amplitude², converting amplitude to dB uses 20×log10.

---

## Step 1.6: Saving Data — `save_samples()` (Lines 262-291)

```python
samples.tofile(filename)   # Raw binary dump — no headers, just I/Q values
```

### 💡 Concept: Binary I/Q File Format

The `.dat` file is a **raw binary dump** of complex64 values. No headers, no metadata. Just a sequence of `[I₀, Q₀, I₁, Q₁, I₂, Q₂, ...]` as 32-bit floats.

This is the standard format used across SDR tools (GNU Radio, MATLAB, etc.). The metadata file `_meta.txt` stores the parameters separately (sample rate, frequency, etc.) — because without knowing these, the binary file is meaningless.

---

# SCRIPT 2: `2_detect_pss_sss.py` — Cell Detection (The Core!)

This is where the real DSP happens. We take the raw captured signal and find which 5G cell towers are present.

---

## Step 2.1: Detection Constants (Lines 20-23)

```python
FFT_SIZE = 256       # NOT the full 2048!
CP_LEN = 20          # Cyclic Prefix length for this FFT size
SAMPLE_RATE = 30.72e6
DETECTION_THRESHOLD_DB = 12.0
```

### 💡 Concept: Why FFT_SIZE = 256 (not 2048)?

The full 5G NR system uses 2048-point FFT. But for **detection purposes**, we use a smaller 256-point FFT. Here's why:

1. **PSS uses only 127 subcarriers** out of the 2048 available. You don't need all 2048 bins to represent 127 values — 256 bins is more than enough (127 < 256).

2. **Speed:** Correlation with a 256-sample reference is ~8× faster than with 2048 samples. Since we're scanning millions of samples, this matters enormously.

3. **Reduced noise:** A smaller FFT means the PSS energy is more concentrated, improving detection SNR.

**CP_LEN = 20:** This is the cyclic prefix length scaled down proportionally. In the full system: CP = 144 samples for FFT=2048. Scaled: 144 × (256/2048) = 18 ≈ 20 (rounded up for margin).

**Detection threshold = 12 dB:** This means a PSS peak must be 12 dB above the noise floor to be accepted as a valid detection. This is a trade-off:
- Lower threshold → detect weaker cells, but risk false alarms
- Higher threshold → only detect strong cells, but miss weak ones

---

## Step 2.2: PSS Generation — `generate_pss()` (Lines 45-69)

```python
def generate_pss(n_id_2):
    # Step 1: Initialize the LFSR
    x = np.array([0, 1, 1, 0, 1, 1, 1])   # 7 initial register values

    # Step 2: Generate the m-sequence
    for i in range(120):
        next_val = (x[i+4] + x[i]) % 2     # Feedback: XOR of positions 0 and 4
        x = np.append(x, next_val)

    # Step 3: Apply cyclic shift and BPSK mapping
    pss_seq = np.zeros(127)
    for n in range(127):
        idx = (n + 43 * n_id_2) % 127      # Cyclic shift by 0, 43, or 86
        pss_seq[n] = 1 - 2 * x[idx]        # BPSK: 0→+1, 1→-1

    return pss_seq  # 127 values, each +1 or -1
```

### 💡 Concept: M-Sequences and Why They're Perfect for Detection

**What is an m-sequence?** It's a binary sequence generated by a **Linear Feedback Shift Register (LFSR)**. Think of it as a string of 127 bits that looks random but is completely deterministic.

**Step 1 — The LFSR:** Imagine 7 boxes in a row, each holding a 0 or 1:

```
Registers: [x₀=0] [x₁=1] [x₂=1] [x₃=0] [x₄=1] [x₅=1] [x₆=1]
```

The initial values `[0,1,1,0,1,1,1]` are specified by 3GPP TS 38.211. They're not arbitrary — using different initial values would produce a different sequence, and the receiver wouldn't match.

**Step 2 — The feedback recurrence:** `x(i+7) = [x(i+4) + x(i)] mod 2`

This comes from the **generator polynomial x⁷ + x⁴ + 1**. What does this polynomial mean? Each term tells you which register positions to XOR:
- x⁷ → the new bit being generated
- x⁴ → tap at position 4
- x⁰ = 1 → tap at position 0

So: `new_bit = bit_at_position_4 ⊕ bit_at_position_0`

We do `(a + b) % 2` which is mathematically equivalent to XOR for bits.

After 120 iterations, we have the full m-sequence: x[0] through x[126] = 127 values.

**Why 127?** An m-sequence of order n has length 2ⁿ - 1. For n=7: 2⁷ - 1 = 127.

**Step 3a — Cyclic shift:** The same base m-sequence is used for all 3 PSS variants. The only difference is a cyclic shift:
- N_ID_2 = 0 → shift by 0
- N_ID_2 = 1 → shift by 43
- N_ID_2 = 2 → shift by 86

**Why 43?** 127 ÷ 3 ≈ 42.3, rounded to 43. This ensures maximum spacing between the three variants, so they're as different from each other as possible → better distinguishability during detection.

**Step 3b — BPSK mapping:** `1 - 2*x[idx]` converts:
- Binary 0 → 1 - 2×0 = **+1**
- Binary 1 → 1 - 2×1 = **-1**

This is BPSK (Binary Phase Shift Keying): the simplest modulation where we just flip the sign. The PSS is intentionally kept simple and robust.

### 💡 The Magic Property — Autocorrelation

This is **the most important concept** for understanding why PSS detection works:

```
When you correlate an m-sequence with itself:

  Aligned (τ=0):      R(0) = 127  ← BIG peak
  Misaligned (τ≠0):   R(τ) = -1   ← essentially zero
```

This means: slide the 127-sample reference along the received signal. At every position where the PSS is NOT present, the correlation is near zero (-1). At the EXACT position where the PSS IS present, the correlation jumps to 127. **You get a sharp spike precisely at the PSS location.**

**Peak-to-sidelobe ratio = 10 × log10(127/1) ≈ 21 dB.** This is why even in moderate noise, the PSS peak stands out clearly.

---

## Step 2.3: Time-Domain PSS — `generate_pss_time_domain()` (Lines 71-92)

```python
def generate_pss_time_domain(n_id_2):
    pss_freq = generate_pss(n_id_2)          # 127 BPSK values in frequency domain

    subcarriers = np.zeros(FFT_SIZE, dtype=complex)   # 256 bins, all zero
    center = FFT_SIZE // 2                             # bin 128
    subcarriers[center-63:center+64] = pss_freq        # Put PSS in center 127 bins

    pss_time = np.fft.ifft(np.fft.ifftshift(subcarriers)) * np.sqrt(FFT_SIZE)
    return pss_time   # 256 complex time-domain samples
```

### 💡 Concept: Mapping PSS onto OFDM Subcarriers

**PSS is defined in the frequency domain** (it's a sequence of values assigned to specific subcarriers). But the captured signal is in the **time domain** (a sequence of I/Q samples). To correlate them, we need both in the same domain.

**Step-by-step what happens:**

1. **Start with 256 zeros** — representing 256 subcarriers, all empty.

2. **Place PSS in the center 127 bins:**
   ```
   bin:    ... 0  0  0 [pss₀ pss₁ ... pss₁₂₆] 0  0  0 ...
   index:    0         65                    191      255
   ```
   The PSS occupies the center of the band, leaving guard bands (zeros) on the edges. This matches how a real cell tower transmits SSB.

3. **`ifftshift`:** In the array, the center is at index 128. But the IFFT expects DC at index 0. `ifftshift` rearranges:
   ```
   Before ifftshift:  [... negative freq | DC | positive freq ...]
                                          ↑ center
   After ifftshift:   [DC | positive freq ... | negative freq ...]
                       ↑ index 0
   ```

4. **`ifft`:** Converts 256 frequency-domain values → 256 time-domain samples. This is exactly what the **transmitter** does in OFDM! We're reconstructing what the cell tower transmitted.

5. **`× √FFT_SIZE`:** Energy normalization. The IFFT divides by N internally; we multiply by √N to match the transmitter's scaling.

**Result:** A 256-sample complex waveform that represents one OFDM symbol carrying only the PSS.

---

## Step 2.4: PSS Detection — `detect_pss()` (Lines 131-178)

```python
def detect_pss(rx_signal, threshold_db=DETECTION_THRESHOLD_DB):
    detections = []

    for n_id_2 in range(3):                          # Try all 3 PSS variants
        pss_ref = generate_pss_time_domain(n_id_2)   # Generate reference

        # Cross-correlate received signal with reference
        correlation = np.abs(signal.correlate(rx_signal, pss_ref, mode='valid'))

        # Find the peak
        peak_idx = np.argmax(correlation)
        peak_value = correlation[peak_idx]

        # Estimate noise floor (exclude region around peak)
        noise_indices = np.ones(len(correlation), dtype=bool)
        noise_indices[max(0, peak_idx-1000):min(len(correlation), peak_idx+1000)] = False
        noise_avg = np.mean(correlation[noise_indices])

        # Calculate SNR
        snr_db = 20 * np.log10(peak_value / noise_avg) if noise_avg > 0 else 0

        if snr_db > threshold_db:
            detections.append((n_id_2, peak_idx, snr_db, peak_value))

    detections.sort(key=lambda x: x[2], reverse=True)  # Sort by SNR
    return detections
```

### 💡 Concept: Cross-Correlation as a "Sliding Pattern Match"

This is the heart of the detector. Here's what happens conceptually:

```
Received signal:  ~~~~~~~~[PSS IS HERE]~~~~~~~~~~~~~~~~~~~~
                  sample 0    ↑ sample 50000            sample 153M
                           (we don't know this yet)

Reference:        [PSS pattern]    (256 samples)

Step 1: Place reference at start:
  correlation[0] = sum(rx[0:256] × ref*)     → small value (no PSS here)

Step 2: Slide one sample:
  correlation[1] = sum(rx[1:257] × ref*)     → small value

... keep sliding ...

Step 50000: Place reference at the PSS position:
  correlation[50000] = sum(rx[50000:50256] × ref*)  → HUGE VALUE! (PSS found!)

... continue sliding ...
```

**`signal.correlate(rx, ref, mode='valid')`:** This does exactly the sliding operation above. `mode='valid'` means only compute correlations where the reference fully overlaps the signal (no padding).

Internally, `scipy.signal.correlate` uses **FFT-based correlation** for large signals:
```
R_xy = IFFT(FFT(x) × conj(FFT(y)))
```
This is O(N log N) instead of O(N²) — crucial when N = 153 million!

**Noise floor estimation:** We mask out ±1000 samples around the peak (because the peak and its immediate neighbors have elevated values), then average everything else to get the noise floor.

**SNR = 20 × log10(peak / noise):** We use 20× because we're working with amplitudes (not power). This is the detection SNR — how much the PSS peak sticks out above the noise.

**Why try all 3?** We don't know which cell tower (if any) is nearby. Each cell tower uses one of the 3 PSS variants (N_ID_2 = 0, 1, or 2). We try all three and keep those that exceed the threshold.

---

## Step 2.5: SSS Generation — `generate_sss()` (Lines 96-127)

```python
def generate_sss(n_id_1, n_id_2):
    # TWO different m-sequences this time
    x0 = np.array([1, 0, 0, 0, 0, 0, 0])   # Initial state for sequence 0
    x1 = np.array([1, 0, 0, 0, 0, 0, 0])   # Initial state for sequence 1

    for i in range(120):
        x0 = np.append(x0, (x0[i+4] + x0[i]) % 2)   # Polynomial: x⁷ + x⁴ + 1
        x1 = np.append(x1, (x1[i+1] + x1[i]) % 2)   # Polynomial: x⁷ + x¹ + 1  ← DIFFERENT!

    # Encode cell ID into cyclic shift indices
    m0 = 15 * (n_id_1 // 112) + (5 * n_id_2)   # Encodes both N_ID_1 and N_ID_2
    m1 = n_id_1 % 112                            # Encodes N_ID_1

    # Generate SSS as product of two shifted m-sequences
    sss_seq = np.zeros(127)
    for n in range(127):
        d0 = 1 - 2 * x0[(n + m0) % 127]     # BPSK-mapped, shifted by m0
        d1 = 1 - 2 * x1[(n + m1) % 127]     # BPSK-mapped, shifted by m1
        sss_seq[n] = d0 * d1                 # Element-wise product

    return sss_seq
```

### 💡 Concept: SSS — Why It's More Complex Than PSS

**PSS tells us the sector (N_ID_2 = 0, 1, or 2)** — but that's only 3 possibilities. To uniquely identify a cell, we need the **cell group (N_ID_1 = 0 to 335)**. That's 336 more possibilities. Combined:

```
Physical Cell ID (PCI) = 3 × N_ID_1 + N_ID_2

Total unique PCIs: 3 × 336 = 1008 (numbered 0 to 1007)
```

**Why two m-sequences?** A single m-sequence with cyclic shifts can only produce 127 different sequences (shifts 0 to 126). But we need 336 × 3 = 1008 unique sequences! By taking the **product of two independently shifted m-sequences**, we can create many more unique combinations:
- m0 can take values 0 to ~167 (depends on N_ID_1 and N_ID_2)
- m1 can take values 0 to 111 (depends on N_ID_1)

The product `d0 × d1` where each is ±1 gives a new ±1 sequence whose identity encodes the specific (N_ID_1, N_ID_2) pair.

**Different generator polynomials:**
- x0: x⁷ + x⁴ + 1 → feedback `x0[i+4] + x0[i]` (same as PSS)
- x1: x⁷ + x¹ + 1 → feedback `x1[i+1] + x1[i]` (different!)

Using different polynomials ensures x0 and x1 are mathematically independent, giving better cross-correlation properties between different SSS sequences.

**Index encoding — working backwards:**
- From N_ID_1 and N_ID_2, we compute m0 and m1
- m0 encodes a combination of both IDs
- m1 encodes just N_ID_1 modulo 112

The formulas `m0 = 15×⌊N_ID_1/112⌋ + 5×N_ID_2` and `m1 = N_ID_1 mod 112` ensure every valid (N_ID_1, N_ID_2) pair maps to a unique (m0, m1) pair.

---

## Step 2.6: SSS Detection — `detect_sss()` (Lines 182-224)

```python
def detect_sss(rx_signal, pss_timing, n_id_2):
    # Step 1: Find where SSS should be in the signal
    symbol_len = FFT_SIZE + CP_LEN          # 256 + 20 = 276 samples per OFDM symbol
    sss_start = pss_timing + 2 * symbol_len # SSS is 2 symbols after PSS

    # Step 2: Extract the SSS OFDM symbol
    sss_rx = rx_signal[sss_start:sss_start+FFT_SIZE]   # 256 samples

    # Step 3: Convert to frequency domain
    sss_rx_freq = np.fft.fftshift(np.fft.fft(sss_rx)) / np.sqrt(FFT_SIZE)

    # Step 4: Extract the 127 subcarriers carrying SSS
    center = FFT_SIZE // 2
    sss_rx_127 = sss_rx_freq[center-63:center+64]

    # Step 5: Brute-force search over all 336 possible N_ID_1 values
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

### 💡 Concept: SSS Detection Step-by-Step

**Step 1 — Timing:** We already know where the PSS is (from Step 2.4). In the SSB (Synchronization Signal Block), the structure is:

```
Symbol 0: PSS           ← We found this
Symbol 1: PBCH
Symbol 2: SSS + PBCH    ← SSS is here
Symbol 3: PBCH
```

So SSS is exactly 2 OFDM symbols after PSS. One OFDM symbol = FFT_SIZE + CP_LEN = 276 samples. Therefore: `sss_start = pss_timing + 2 × 276 = pss_timing + 552`.

**Step 2 — Extract SSS:** We take exactly 256 samples starting at the SSS position. We skip the CP (it's a guard interval and not needed for demodulation).

**Step 3 — FFT:** Here we go from time → frequency domain. This is what the **receiver** does:
```
Received time samples → FFT → Frequency domain values on each subcarrier
```

`fftshift` puts DC in the center. Division by `√N` normalizes the energy.

**Step 4 — Extract center 127:** Just like PSS occupied 127 subcarriers in the center, SSS also occupies the center 127. We throw away the guard band subcarriers (which are mostly noise anyway).

**Step 5 — Exhaustive search:** This is the brute-force approach:
- Generate all 336 possible SSS reference sequences
- Correlate each one with the received SSS
- The one with highest correlation is the correct N_ID_1

**`np.sum(sss_rx_127 * np.conj(sss_ref))`:** This is a **frequency-domain correlation** (also called the inner product or dot product). For each subcarrier:
- Multiply received value by the conjugate of the reference
- Sum all 127 products

If the received SSS matches the reference, all 127 products add constructively → large value.
If it doesn't match, products are random ±1 and tend to cancel → small value.

**Why frequency domain here (not time domain like PSS)?** PSS detection used time-domain correlation because we didn't know the timing. We had to slide across millions of samples. But for SSS, we already know the exact timing from PSS! So we can extract the one relevant symbol, FFT it, and do a quick 127-point dot product. Much faster.

---

## Step 2.7: CFO Estimation — `estimate_cfo()` (Lines 228-256)

```python
def estimate_cfo(rx_signal, pss_timing):
    cp_start = pss_timing - CP_LEN                              # CP starts before the symbol

    cp_early = rx_signal[cp_start:cp_start+CP_LEN]              # The CP itself (20 samples)
    cp_late  = rx_signal[cp_start+FFT_SIZE:cp_start+FFT_SIZE+CP_LEN]  # The symbol tail (20 samples)

    corr = np.sum(cp_late * np.conj(cp_early))                  # Complex correlation

    cfo = np.angle(corr) / (2 * np.pi)                          # Normalized CFO
    return cfo
```

### 💡 Concept: Carrier Frequency Offset (CFO) and Why It Matters

**What is CFO?** The cell tower transmits at exactly 3,500,000,000 Hz. But your USRP's local oscillator might be tuned to 3,500,000,023 Hz. That 23 Hz difference is the CFO.

**Why does it happen?** No oscillator is perfect. Crystal oscillators have parts-per-million (ppm) accuracy. At 3.5 GHz, even 1 ppm = 3,500 Hz offset!

**What does CFO do to the signal?** It adds a spinning phase rotation to every sample:

```
received(n) = transmitted(n) × e^(j·2π·Δf·n/Fs)
```

As n increases, the phase rotates more and more. This causes:
1. **Phase rotation** of all subcarriers (bad for demodulation)
2. **Inter-Carrier Interference (ICI)** because subcarrier orthogonality is broken

**The CP Trick — How This Code Estimates CFO:**

The key insight is that the Cyclic Prefix is a **copy** of the last CP_LEN samples of the OFDM symbol:

```
OFDM Symbol structure:
[CP region] [........Main symbol........]
  ↑ These samples are identical to ↑ these samples (the tail)
  cp_early                          cp_late
```

Without CFO: `cp_early[i] = cp_late[i]` exactly.

With CFO: `cp_late[i] = cp_early[i] × e^(j·2π·Δf·N/Fs)` — there's a constant phase rotation between the two copies, proportional to the time gap between them (N = FFT_SIZE samples).

```
corr = Σ cp_late[i] × conj(cp_early[i])
     = Σ |cp_early[i]|² × e^(j·2π·Δf·N/Fs)     [since s(i+N) × s*(i) = |s|² × e^(jφ)]
     = P × e^(jφ)
```

So `angle(corr) = φ = 2π·Δf·N/Fs`

And `cfo_normalized = φ / (2π) = Δf·N/Fs = Δf/SCS`

**To convert to Hz:** `Δf = cfo_normalized × SCS = cfo_normalized × 15000 Hz`

**Limitation:** This method can only detect CFO up to ±0.5 × SCS = ±7.5 kHz. Larger offsets cause the phase to wrap around.

---

## Step 2.8: RSRP Calculation — `calculate_rsrp()` (Lines 260-284)

```python
def calculate_rsrp(rx_signal, pss_timing, peak_power):
    pss_symbol = rx_signal[pss_timing:pss_timing+FFT_SIZE]  # Extract PSS symbol

    power_per_re = np.mean(np.abs(pss_symbol)**2)           # Average power per Resource Element

    rsrp_dbm = 10 * np.log10(power_per_re) + 30             # Convert to dBm
    return rsrp_dbm
```

### 💡 Concept: RSRP — The Standard Signal Strength Metric

**RSRP (Reference Signal Received Power)** defined in 3GPP TS 38.215 is the linear average power of the resource elements carrying reference signals (like PSS).

**Resource Element (RE):** One subcarrier in one OFDM symbol = the smallest unit of the OFDM grid.

**`np.mean(np.abs(pss_symbol)**2)`:** Average the power of all 256 time-domain samples in the PSS symbol. This gives the average power per RE.

**What does the RSRP value tell you?**

| RSRP (dBm)  | Meaning            | Real-world scenario          |
|-------------|--------------------|-----------------------------|
| > -80       | Excellent          | Standing near a tower       |
| -80 to -90  | Good               | Outdoor, clear line-of-sight|
| -90 to -100 | Fair               | Indoor, through walls       |
| -100 to -110| Poor               | Cell edge, deep indoor      |
| < -110      | Very poor          | Handover urgently needed    |

This is the same RSRP value you'd see in a professional network measurement tool like a Rohde & Schwarz scanner.

---

## Step 2.9: The Full Detection Pipeline — `detect_cells()` (Lines 288-354)

```python
def detect_cells(rx_signal):
    # Stage 1: PSS Detection
    pss_detections = detect_pss(rx_signal)

    for n_id_2, timing, snr_db, peak_power in pss_detections:
        # Stage 2: SSS Detection (using PSS timing)
        n_id_1, sss_corr = detect_sss(rx_signal, timing, n_id_2)

        # Stage 3: Calculate PCI
        pci = 3 * n_id_1 + n_id_2

        # Stage 4: CFO Estimation
        cfo = estimate_cfo(rx_signal, timing)

        # Stage 5: RSRP Measurement
        rsrp = calculate_rsrp(rx_signal, timing, peak_power)

        # Package results
        cell = DetectedCell(pci=pci, n_id_1=n_id_1, n_id_2=n_id_2,
                           timing_offset=timing, snr_db=snr_db,
                           rsrp_dbm=rsrp, cfo_estimate=cfo)
        detected_cells.append(cell)

    return detected_cells
```

### 💡 Concept: The Detection Hierarchy

This function is the **pipeline orchestrator**. It mirrors exactly what a real UE (phone) does during **cell search** (3GPP TS 38.213):

```
┌──────────────────────────────────────────────────────────────┐
│  Stage 1: PSS Detection                                      │
│  • Input:  Raw I/Q samples (millions of them)                │
│  • Method: Time-domain correlation with 3 known PSS patterns │
│  • Output: Timing (where is the SSB?) + N_ID_2 (0, 1, or 2) │
│  • This is the COARSEST search — we find the needle in the   │
│    haystack by sliding the PSS template across 153M samples  │
└─────────────────────────┬────────────────────────────────────┘
                          │ timing + N_ID_2
                          ▼
┌──────────────────────────────────────────────────────────────┐
│  Stage 2: SSS Detection                                      │
│  • Input:  Exact location of SSS symbol (from PSS timing)    │
│  • Method: Freq-domain correlation with 336 SSS patterns     │
│  • Output: N_ID_1 (0 to 335)                                │
│  • Now we know WHICH cell: PCI = 3 × N_ID_1 + N_ID_2       │
└─────────────────────────┬────────────────────────────────────┘
                          │ N_ID_1 → PCI
                          ▼
┌──────────────────────────────────────────────────────────────┐
│  Stage 3: CFO + RSRP                                         │
│  • CFO from CP correlation → frequency offset                │
│  • RSRP from PSS symbol power → signal strength             │
│  • These provide quality metrics for the detected cell       │
└──────────────────────────────────────────────────────────────┘
```

**Key insight:** Each stage uses the output of the previous stage. PSS gives us timing and N_ID_2. We can't detect SSS without knowing the timing first. And we can't calculate PCI without both N_ID_1 (from SSS) and N_ID_2 (from PSS).

---

# SCRIPT 3: `3_visualize_results.py` — Results Visualization

This script reads the JSON output from Script 2 and creates plots + reports.

---

## Step 3.1: Loading Results (Lines 19-23)

```python
def load_results(filename):
    with open(filename, 'r') as f:
        data = json.load(f)
    return data
```

The JSON file looks like:
```json
{
  "num_cells": 3,
  "cells": [
    {"pci": 215, "n_id_1": 71, "n_id_2": 2, "timing_offset": 14073828,
     "snr_db": 22.6, "rsrp_dbm": -27.0, "cfo_estimate": 0.002399}
  ]
}
```

---

## Step 3.2: The Summary Plot — `create_summary_plot()` (Lines 27-165)

Six sub-plots are created:

| Plot | What It Shows | Why It Matters |
|------|---------------|----------------|
| **RSRP Bar Chart** | Signal strength per cell | Which cell is closest/strongest |
| **SNR Bars** | Detection confidence | How reliable the detection is |
| **CFO Scatter** | Frequency offset per cell | Oscillator quality / Doppler |
| **Timing Scatter** | PSS position in samples | Which cell transmits first (distance) |
| **N_ID_2 Pie Chart** | PSS sector distribution | How sectors are allocated |
| **Details Table** | All metrics in one table | Quick reference |

### 💡 Concept: What You Can Learn From Each Plot

**RSRP ranking:** The cell with highest RSRP is typically the one your phone would connect to. In a handover scenario, the UE measures RSRP from neighboring cells and reports to the network.

**Timing offsets:** If two cells have very different timing offsets, they are at different distances. Sound travels at the speed of light: `distance = timing_difference × c / (2 × sample_rate)`.

**CFO values:** Small CFOs (< 0.01 normalized) are normal. If one cell shows a much larger CFO, it could indicate a **fake base station** (IMSI catcher) — because attackers often use cheaper oscillators.

---

## Step 3.3: Detailed Report — `print_detailed_report()` (Lines 169-230)

```python
# Signal quality assessment
if cell['rsrp_dbm'] > -80:
    quality = "EXCELLENT"
elif cell['rsrp_dbm'] > -90:
    quality = "GOOD"
elif cell['rsrp_dbm'] > -100:
    quality = "FAIR"
else:
    quality = "WEAK"

# CFO in Hz
cfo_hz = cell['cfo_estimate'] * 15000   # Convert from normalized to Hz
```

### 💡 Concept: Converting Normalized CFO to Hz

`cfo_estimate` is the **normalized CFO** — the frequency offset expressed as a fraction of the subcarrier spacing:

```
ε = Δf / SCS

Therefore: Δf = ε × SCS = cfo_estimate × 15,000 Hz
```

If cfo_estimate = 0.002399, then Δf = 0.002399 × 15000 ≈ 36 Hz. This is a very small offset — typical for a real cell tower with a high-quality oscillator.

---

# SUMMARY: End-to-End Flow in One Table

| Step | Code Location | What Happens | Key Concept |
|------|--------------|--------------|-------------|
| 1 | `1_capture_5g.py:connect_usrp()` | Configure SDR hardware | I/Q sampling, Nyquist, downconversion |
| 2 | `1_capture_5g.py:capture_samples()` | Record raw radio signals | Complex baseband, streaming |
| 3 | `1_capture_5g.py:quick_analysis()` | Check if signal is present | dBm, PAPR, OFDM characteristics |
| 4 | `2_detect_pss_sss.py:generate_pss()` | Create PSS reference | m-sequences, LFSR, BPSK, TS 38.211 |
| 5 | `2_detect_pss_sss.py:generate_pss_time_domain()` | Convert PSS to time domain | OFDM modulation, IFFT, subcarrier mapping |
| 6 | `2_detect_pss_sss.py:detect_pss()` | Find PSS in captured signal | Cross-correlation, SNR, autocorrelation |
| 7 | `2_detect_pss_sss.py:generate_sss()` | Create SSS reference | Gold codes, dual m-sequences, PCI encoding |
| 8 | `2_detect_pss_sss.py:detect_sss()` | Find SSS to get cell group | FFT demodulation, SSB structure, frequency-domain correlation |
| 9 | `2_detect_pss_sss.py:estimate_cfo()` | Measure frequency offset | Cyclic prefix, phase recovery, oscillator error |
| 10 | `2_detect_pss_sss.py:calculate_rsrp()` | Measure signal strength | RSRP definition, power measurement, TS 38.215 |
| 11 | `3_visualize_results.py` | Visualize & report | RSRP quality bands, cell ranking |

---

> **Key takeaway:** Everything connects. The m-sequence properties make PSS detection reliable. The OFDM structure enables SSS extraction via FFT. The cyclic prefix — designed to fight multipath — doubles as a CFO estimator. Every "theoretical" concept is directly implemented in the code, and every line of code traces back to a specific 3GPP specification or DSP principle.

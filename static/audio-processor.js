/**
 * BolKhata AI — AudioWorkletProcessor (`static/audio-processor.js`)
 *
 * Captures browser microphone Float32 audio at the native AudioContext sample rate
 * (e.g. 48kHz / 44.1kHz or 16kHz), downsamples to 16,000 Hz 16-bit signed mono PCM,
 * batches ~100ms chunks (1,600 samples = 3,200 bytes), and emits lightweight
 * RMS voice activity transitions (`speech_start` / `speech_end`) so the client
 * can measure end-of-speech -> first-audio-byte latency accurately.
 */

class BolKhataPCMProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.targetSampleRate = 16000;
    this.chunkSizeSamples = 1600; // 100ms at 16kHz
    this.pcmBuffer = new Int16Array(this.chunkSizeSamples);
    this.bufferIndex = 0;

    // Lightweight Voice Activity Detection (VAD) state for latency timing
    this.isSpeaking = false;
    this.silenceFrames = 0;
    this.rmsThreshold = 0.015;
    this.silenceFramesThreshold = 45; // ~120ms of silence after speech
  }

  /**
   * Downsample Float32Array from native sampleRate to 16kHz and convert to Int16.
   */
  _downsampleAndQueue(inputChannel) {
    const ratio = sampleRate / this.targetSampleRate;
    let sumSq = 0;

    for (let i = 0; i < inputChannel.length; i++) {
      const s = inputChannel[i];
      sumSq += s * s;
    }
    const rms = Math.sqrt(sumSq / (inputChannel.length || 1));

    if (rms > this.rmsThreshold) {
      this.silenceFrames = 0;
      if (!this.isSpeaking) {
        this.isSpeaking = true;
        this.port.postMessage({ type: "vad_speech_start", rms });
      }
    } else if (this.isSpeaking) {
      this.silenceFrames++;
      if (this.silenceFrames >= this.silenceFramesThreshold) {
        this.isSpeaking = false;
        this.silenceFrames = 0;
        this.port.postMessage({ type: "vad_speech_end" });
      }
    }

    if (Math.abs(ratio - 1.0) < 0.01) {
      for (let i = 0; i < inputChannel.length; i++) {
        this._pushSample(inputChannel[i]);
      }
      return;
    }

    const outputLength = Math.floor(inputChannel.length / ratio);
    for (let i = 0; i < outputLength; i++) {
      const start = Math.floor(i * ratio);
      const end = Math.min(Math.floor((i + 1) * ratio), inputChannel.length);
      let acc = 0;
      let count = 0;
      for (let j = start; j < end; j++) {
        acc += inputChannel[j];
        count++;
      }
      const avgSample = count > 0 ? acc / count : inputChannel[start] || 0;
      this._pushSample(avgSample);
    }
  }

  _pushSample(floatSample) {
    const clamped = Math.max(-1, Math.min(1, floatSample));
    const int16 = clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff;
    this.pcmBuffer[this.bufferIndex++] = int16;

    if (this.bufferIndex >= this.chunkSizeSamples) {
      const outgoing = this.pcmBuffer.slice(0);
      this.port.postMessage(
        {
          type: "pcm_chunk",
          buffer: outgoing.buffer,
        },
        [outgoing.buffer]
      );
      this.bufferIndex = 0;
    }
  }

  process(inputs) {
    const input = inputs[0];
    if (input && input.length > 0 && input[0].length > 0) {
      this._downsampleAndQueue(input[0]);
    }
    return true;
  }
}

registerProcessor("bolkhata-pcm-processor", BolKhataPCMProcessor);

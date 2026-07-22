import type { AdaptiveSamplingConfig, SamplingInput, SamplingQueue } from "./types";

export class AdaptiveSamplingService {
  private readonly window: SamplingInput[] = [];
  private readonly windowSize: number;

  constructor(
    private readonly queue: SamplingQueue,
    config: AdaptiveSamplingConfig,
  ) {
    this.windowSize = config.windowSize;
  }

  async process(input: SamplingInput): Promise<boolean> {
    this.window.push(input);

    if (this.window.length < this.windowSize) {
      return false;
    }

    const index = Math.floor(Math.random() * this.windowSize);
    const selected = this.window[index];

    await this.queue.enqueue(selected);
    this.window.length = 0;

    return true;
  }
}

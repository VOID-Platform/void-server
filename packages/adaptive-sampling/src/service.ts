import type { AdaptiveSamplingConfig, SamplingInput, SamplingQueue } from "./types";

export class AdaptiveSamplingService {
  private readonly window: SamplingInput[] = [];
  private readonly windowSize: number;

  constructor(
    private readonly queue: SamplingQueue,
    config: AdaptiveSamplingConfig,
  ) {
    const windowSize = config.windowSize ?? 20;
    if (!Number.isInteger(windowSize) || windowSize < 1) {
      throw new Error(`windowSize must be a positive integer, got ${windowSize}`);
    }
    this.windowSize = windowSize;
  }

  async process(input: SamplingInput): Promise<boolean> {
    this.window.push(input);

    if (this.window.length < this.windowSize) {
      return false;
    }

    const batch = this.window.splice(0, this.windowSize);
    const index = Math.floor(Math.random() * this.windowSize);
    const selected = batch[index];

    await this.queue.enqueue(selected);

    return true;
  }
}

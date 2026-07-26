export class LatestRequestGate {
  private generation = 0;
  private query = "";

  invalidate(query: string): void {
    this.query = query;
    this.generation += 1;
  }

  begin(query: string, append: boolean): number | null {
    if (append && query !== this.query) return null;
    if (!append) this.query = query;
    this.generation += 1;
    return this.generation;
  }

  isCurrent(generation: number, query: string): boolean {
    return generation === this.generation && query === this.query;
  }
}

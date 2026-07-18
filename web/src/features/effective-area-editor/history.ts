export class GeometryHistory<T> {
  private entries: T[];
  private index = 0;

  constructor(initial: T, private readonly limit = 100) {
    this.entries = [clone(initial)];
  }

  current(): T {
    return clone(this.entries[this.index]);
  }

  push(value: T): T {
    const next = clone(value);
    if (same(this.entries[this.index], next)) return this.current();
    this.entries = [...this.entries.slice(0, this.index + 1), next];
    if (this.entries.length > this.limit + 1) this.entries.shift();
    this.index = this.entries.length - 1;
    return this.current();
  }

  undo(): T | null {
    if (this.index === 0) return null;
    this.index -= 1;
    return this.current();
  }

  redo(): T | null {
    if (this.index >= this.entries.length - 1) return null;
    this.index += 1;
    return this.current();
  }
}

function same<T>(left: T, right: T): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

/**
 * Bounded recursive generic invariant solver.
 * Resolves nested state transitions with a recursion depth limit to prevent infinite expansion.
 */
type PrevCount = [never, 0, 1, 2, 3, 4, 5];

export type DeepInfiniteResolve<T, Depth extends number = 5> = PrevCount[Depth] extends never
  ? T
  : T extends (...args: any[]) => infer R
  ? DeepInfiniteResolve<R, PrevCount[Depth]>
  : T extends object
  ? { [K in keyof T]: DeepInfiniteResolve<T[K], PrevCount[Depth]> }
  : T;

export interface StateGraphNode {
  id: string;
  payload: Record<string, any>;
  next: StateGraphNode;
  compute: () => StateGraphNode;
}

export type SolvedState = DeepInfiniteResolve<StateGraphNode>;
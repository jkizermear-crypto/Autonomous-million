# TypeScript proposal — untested

Source: https://github.com/Senthemodder/aquarium-of-gullibles/blob/main/src/types/state.ts
No external pull request was created. No third-party code was executed.
Static checks are not proof of TypeScript correctness.

## Rationale
The original type definition caused unbounded recursive type expansion due to self-intersection (`& DeepInfiniteResolve<T>`) and cyclic references in `StateGraphNode`. By introducing a depth counter tuple (`PrevCount`), recursion is safely bounded to a maximum depth, preventing TypeScript compiler stack overflows while maintaining the public export names and structure.

## Limitations
Deeply nested structures exceeding the maximum depth limit (5 levels) will stop resolving further properties, treating them as their raw types at the boundary.

## Suggested tests
- Should correctly resolve properties of StateGraphNode up to the allowed recursion depth without causing a compiler error.
- Should preserve exported types DeepInfiniteResolve, StateGraphNode, and SolvedState.
- Should safely handle circular references like StateGraphNode.next without hitting maximum instantiation depth limits.

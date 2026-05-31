"""Shared topological-sort utility for the crypto FIFO engine."""

from __future__ import annotations

import heapq


def topological_sort_with_fallback(
    nodes: set[str],
    forward_edges: dict[str, set[str]],
) -> tuple[list[str], list[str]]:
    """Kahn's topological sort with alphabetical tie-breaking and cycle detection.

    Returns:
        Tuple of (ordered_nodes, cyclic_nodes). ordered_nodes are in topological
        order. cyclic_nodes are nodes involved in cycles, returned in alphabetical
        order. Callers are responsible for logging cycle warnings.
    """
    sorted_nodes = sorted(nodes)

    in_degree: dict[str, int] = dict.fromkeys(sorted_nodes, 0)
    for node in sorted_nodes:
        for successor in forward_edges.get(node, set()):
            if successor in in_degree:
                in_degree[successor] += 1

    heap = [n for n in sorted_nodes if in_degree[n] == 0]
    heapq.heapify(heap)

    result: list[str] = []
    while heap:
        node = heapq.heappop(heap)
        result.append(node)
        for successor in sorted(forward_edges.get(node, set())):
            if successor in in_degree:
                in_degree[successor] -= 1
                if in_degree[successor] == 0:
                    heapq.heappush(heap, successor)

    cyclic = sorted(n for n in sorted_nodes if n not in set(result))
    return result, cyclic

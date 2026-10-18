/**
 * Task blocks on an item sheet, found from the hidden kind column.
 * `kinds[i]` is row i+1's tag. A block runs from its head row through its
 * subtotal row and must have an end row in between.
 */
export function findBlock(kinds, row, blocks) {
  if (row < 1 || row > kinds.length) return null;
  const member = new Set([blocks.head, ...blocks.body, blocks.end, blocks.sub, ""]);
  let head = null;
  for (let r = row; r >= 1; r -= 1) {
    const k = kinds[r - 1] || "";
    if (k === blocks.head) { head = r; break; }
    if (k === blocks.sub && r !== row) return null;     // we are below a closed block
    if (!member.has(k)) return null;
  }
  if (head === null) return null;
  let end = null;
  for (let r = head + 1; r <= kinds.length; r += 1) {
    const k = kinds[r - 1] || "";
    if (k === blocks.end && end === null) end = r;
    else if (k === blocks.sub) return end !== null && row <= r ? { head, end, sub: r } : null;
    else if (k === blocks.head || !member.has(k)) return null;
  }
  return null;
}

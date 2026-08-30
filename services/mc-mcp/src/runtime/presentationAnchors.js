function centeredPosition(position) {
  if (!position || !['x', 'y', 'z'].every((axis) => Number.isFinite(position[axis]))) {
    return null;
  }
  return {
    x: Number(position.x) + 0.5,
    y: Number(position.y) + 0.5,
    z: Number(position.z) + 0.5,
  };
}


export async function presentBlockTarget({
  context,
  phase,
  position,
  ordinal = 0,
  data = {},
  kind = 'block',
}) {
  const centered = centeredPosition(position);
  if (!centered) return null;
  const target = { kind, position: centered };
  context?.report_phase?.(phase, { ...data, target });
  await context?.presentation?.focus?.({ phase, ordinal, target: centered });
  return target;
}


export async function presentHeldItem({ context, itemName, ordinal = 0 }) {
  if (typeof itemName !== 'string' || itemName.length < 1) return null;
  const target = { kind: 'held_item', name: itemName };
  context?.report_phase?.('verifying', { target });
  await context?.presentation?.focusHeldItem?.({
    phase: 'verifying',
    ordinal,
    itemName,
  });
  return target;
}

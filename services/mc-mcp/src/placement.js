export function normalizePlacementBlockName(blockType) {
  return String(blockType).replace(/^minecraft:/, '');
}

const PLACEMENT_YAW = Object.freeze({
  // Beds extend from the foot in the placing player's horizontal look direction.
  // Mineflayer uses 0 for north and rotates clockwise toward west.
  north: 0,
  south: Math.PI,
  east: -Math.PI / 2,
  west: Math.PI / 2,
});

export async function orientForPlacement(bot, blockName, facing = 'north') {
  if (!String(blockName).endsWith('_bed')) return;
  const yaw = PLACEMENT_YAW[facing];
  if (yaw === undefined) throw new Error(`Unsupported placement facing: ${facing}`);
  await bot.look(yaw, 0);
}

export async function placeOrientedBlock(bot, placement, blockName, facing = 'north') {
  await orientForPlacement(bot, blockName, facing);
  if (!String(blockName).endsWith('_bed')) {
    return bot.placeBlock(placement.reference, placement.face);
  }
  if (typeof bot._placeBlockWithOptions !== 'function') {
    throw new Error('Mineflayer oriented placement API is unavailable');
  }
  // The public placeBlock method looks at the clicked face immediately before
  // sending the packet, which overwrites the yaw that controls bed direction.
  return bot._placeBlockWithOptions(placement.reference, placement.face, {
    forceLook: 'ignore',
    swingArm: 'right',
  });
}

function isFullCubeReference(reference) {
  return Array.isArray(reference?.shapes) && reference.shapes.some(shape => (
    Array.isArray(shape)
    && shape.length === 6
    && shape[0] === 0
    && shape[1] === 0
    && shape[2] === 0
    && shape[3] === 1
    && shape[4] === 1
    && shape[5] === 1
  ));
}

export function findPlacementReference(bot, targetPosition, VectorClass) {
  const faces = [
    [0, 1, 0],
    [1, 0, 0],
    [-1, 0, 0],
    [0, 0, 1],
    [0, 0, -1],
    [0, -1, 0],
  ];
  const candidates = [];
  for (const [x, y, z] of faces) {
    const referencePosition = targetPosition.offset(-x, -y, -z);
    const reference = bot.blockAt(referencePosition);
    if (!reference || ['air', 'water', 'lava'].includes(reference.name)) continue;
    candidates.push({ reference, face: new VectorClass(x, y, z) });
  }
  return candidates.find(candidate => isFullCubeReference(candidate.reference))
    || candidates[0]
    || null;
}

export function placementMutation(
  blockType,
  position,
  dimension = 'minecraft:overworld',
) {
  const normalizedBlock = String(blockType).includes(':')
    ? String(blockType)
    : `minecraft:${blockType}`;
  const normalizedDimension = String(dimension).includes(':')
    ? String(dimension)
    : `minecraft:${dimension}`;
  return {
    kind: 'block',
    subject: `block:${normalizedDimension}:${position.x}:${position.y}:${position.z}`,
    delta: 1,
    details: { block_type: normalizedBlock },
  };
}

export function placementMutations(
  blockType,
  position,
  dimension = 'minecraft:overworld',
  observedSecondaryPositions = [],
) {
  const mutations = [placementMutation(blockType, position, dimension)];
  const normalizedBlock = normalizePlacementBlockName(blockType);
  if (normalizedBlock.endsWith('_door')) {
    mutations.push(placementMutation(
      blockType,
      position.offset(0, 1, 0),
      dimension,
    ));
  } else if (normalizedBlock.endsWith('_bed')) {
    mutations.push(...observedSecondaryPositions.map(secondary => (
      placementMutation(blockType, secondary, dimension)
    )));
  }
  return mutations;
}

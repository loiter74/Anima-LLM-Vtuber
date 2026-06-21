/**
 * Memory graph types and parsing functions for the knowledge graph visualization.
 *
 * Converts Memory V2 API page data (WikiPageEntry shape) into d3-force-compatible
 * graph structures. Designed around the actual `on_get_wiki_pages` handler in
 * `src/animetta/orchestration/server/routes.py`.
 *
 * The API currently returns:
 *   { path, title, page_type, content, tags, updated_at }
 *
 * When relations and salience are added to the serialization, these parsers
 * will consume them transparently.
 */

import type { SimulationNodeDatum } from 'd3-force'

// ── Graph node (extends d3-force SimulationNodeDatum for layout) ───────

export interface MemoryNode extends SimulationNodeDatum {
  id: string
  label: string
  category: string       // derived from page_type
  importance: number     // 0-1, determines node radius (8-32px)
  content: string        // full page content for detail panel
  metadata: Record<string, any>
}

// ── Graph edge ─────────────────────────────────────────────────────────

export interface MemoryEdge {
  source: string         // node id
  target: string         // node id
  type: string           // relation_type from backend
  weight: number         // 0-1, determines stroke width
  label: string          // human-readable relation description
}

// ── Combined graph data ────────────────────────────────────────────────

export interface MemoryGraphData {
  nodes: MemoryNode[]
  edges: MemoryEdge[]
}

// ── Internal: shape of a page from the API (with optional future fields)

interface RawPage {
  path: string
  title: string
  page_type: string
  content: string
  tags: string[]
  updated_at: string
  // Optional: added when backend serializes atom.salience
  salience?: number
  // Optional: added when backend serializes atom.relations
  relations?: Array<{
    source_id: string
    target_id: string
    relation_type: string
    metadata?: Record<string, any>
  }>
}

// ── Internal: shape of a raw relation from the API ─────────────────────

interface RawRelation {
  source_id: string
  target_id: string
  relation_type: string
  metadata?: Record<string, any>
}

// ── Category mapping ──────────────────────────────────────────────────
// Maps backend layer → page_type → graph category

const PAGE_TYPE_TO_CATEGORY: Record<string, string> = {
  source: 'other',       // RAW layer
  entity: 'fact',        // EPISODIC layer
  concept: 'interest',   // SEMANTIC layer
  synthesis: 'relation', // EMERGENT layer
}

// ── Display color mappings ─────────────────────────────────────────────

export const CATEGORY_COLORS: Record<string, string> = {
  skill: 'var(--c-blue)',
  interest: 'var(--c-accent)',
  fact: 'var(--c-mint)',
  relation: 'var(--c-gold)',
  knowledge: 'var(--c-accent)',
  preference: 'var(--c-blue)',
  other: 'var(--c-text-dim)',
}

export const RELATION_COLORS: Record<string, string> = {
  UPDATES: 'var(--c-accent)',
  EXTENDS: 'var(--c-blue)',
  DERIVES: 'var(--c-mint)',
  EVOKES: 'var(--c-gold)',
  CONTRADICTS: 'var(--c-red, #ef4444)',
  CONSOLIDATED_INTO: 'var(--c-text-dim)',
  relates_to: 'var(--c-text-muted)',
  default: 'var(--c-text-muted)',
}

// ── Human-readable relation labels ─────────────────────────────────────

const RELATION_LABELS: Record<string, string> = {
  UPDATES: 'updates',
  EXTENDS: 'extends',
  DERIVES: 'derives from',
  EVOKES: 'evokes',
  CONTRADICTS: 'contradicts',
  CONSOLIDATED_INTO: 'consolidated into',
}

// ── Helpers ────────────────────────────────────────────────────────────

/**
 * Derive graph category from page_type.
 * Tags are inspected for finer-grained categorization when available.
 */
function deriveCategory(pageType: string, tags: string[]): string {
  // Check tags for more specific categories
  const tagSet = new Set(tags.map((t) => t.toLowerCase()))

  if (tagSet.has('personality') || tagSet.has('skill')) return 'skill'
  if (tagSet.has('preference') || tagSet.has('interest')) return 'interest'
  if (tagSet.has('identity') || tagSet.has('origin_story')) return 'fact'
  if (tagSet.has('core_beliefs') || tagSet.has('catchphrases')) return 'knowledge'

  return PAGE_TYPE_TO_CATEGORY[pageType] ?? 'other'
}

/**
 * Compute importance (0-1) from available signals.
 *
 * Uses salience if present, otherwise heuristics from tags and content length.
 * Returns a value suitable for mapping to node radius (8-32px).
 */
function computeImportance(page: RawPage): number {
  // If backend provides salience, use it directly
  if (typeof page.salience === 'number') {
    return Math.max(0, Math.min(1, page.salience))
  }

  const tagSet = new Set(page.tags.map((t) => t.toLowerCase()))

  // Seed atoms (high confidence) get boosted importance
  let base = 0.4
  if (tagSet.has('seed')) base = 0.7
  if (tagSet.has('core_beliefs') || tagSet.has('catchphrases')) base = 0.8
  if (tagSet.has('identity') || tagSet.has('origin_story')) base = 0.75

  // Longer content suggests more detailed/important knowledge
  const contentBoost = Math.min(0.3, page.content.length / 2000)

  return Math.max(0, Math.min(1, base + contentBoost))
}

/**
 * Normalize a relation type to a display-friendly label.
 */
function relationLabel(relationType: string): string {
  return RELATION_LABELS[relationType] ?? relationType.toLowerCase().replace(/_/g, ' ')
}

/**
 * Create a canonical edge key for deduplication.
 * Treats A→B and B→A as the same undirected edge.
 */
function edgeKey(sourceId: string, targetId: string): string {
  return [sourceId, targetId].sort().join('::')
}

// ── Public API ─────────────────────────────────────────────────────────

/**
 * Convert Memory V2 API pages into graph nodes.
 *
 * Each page maps to one node. The `path` field (which equals `atom.id`
 * on the backend) becomes the node's `id`.
 *
 * @param pages - Array of page objects from `memory:list_pages` response
 * @returns Array of MemoryNode for d3-force simulation
 */
export function parseNodes(pages: RawPage[]): MemoryNode[] {
  return pages.map((page) => ({
    id: page.path,
    label: page.title || page.content.slice(0, 50),
    category: deriveCategory(page.page_type, page.tags),
    importance: computeImportance(page),
    content: page.content,
    metadata: {
      page_type: page.page_type,
      tags: page.tags,
      updated_at: page.updated_at,
    },
  }))
}

/**
 * Flatten all relations from all pages into a deduplicated edge list.
 *
 * Relations from the backend MemoryAtom.relations are directional, but
 * the graph treats them as undirected: A→B and B→A are merged into a
 * single edge. When duplicates exist, the first occurrence wins.
 *
 * If pages don't include `relations` (current API), returns an empty array.
 *
 * @param pages - Array of page objects from `memory:list_pages` response
 * @returns Deduplicated array of MemoryEdge
 */
export function parseEdges(pages: RawPage[]): MemoryEdge[] {
  const seen = new Map<string, MemoryEdge>()

  for (const page of pages) {
    const relations: RawRelation[] = page.relations ?? []

    for (const rel of relations) {
      // Skip self-referential relations
      if (rel.source_id === rel.target_id) continue

      const key = edgeKey(rel.source_id, rel.target_id)

      // First occurrence wins (deduplication)
      if (!seen.has(key)) {
        seen.set(key, {
          source: rel.source_id,
          target: rel.target_id,
          type: rel.relation_type,
          weight: 0.5,
          label: relationLabel(rel.relation_type),
        })
      }
    }
  }

  return Array.from(seen.values())
}

/**
 * Parse a complete Memory V2 API response into graph data.
 *
 * Convenience wrapper combining parseNodes + parseEdges.
 *
 * @param pages - Array of page objects from `memory:list_pages` response
 * @returns MemoryGraphData with nodes and edges
 */
export function parseMemoryGraph(pages: RawPage[]): MemoryGraphData {
  return {
    nodes: parseNodes(pages),
    edges: parseEdges(pages),
  }
}

/**
 * Tests for memory graph types and parsing functions.
 *
 * Mock data matches the actual Memory V2 API response shape from
 * `on_get_wiki_pages` in routes.py:
 *   { path, title, page_type, content, tags, updated_at }
 *
 * Also tests the optional `relations` and `salience` fields that will be
 * added when the backend serialization is extended.
 */

import { describe, it, expect } from 'vitest'
import {
  parseNodes,
  parseEdges,
  parseMemoryGraph,
  CATEGORY_COLORS,
  RELATION_COLORS,
  type MemoryNode,
  type MemoryEdge,
} from '@/types/memoryGraph'

// ── Mock data matching real API shape ──────────────────────────────────

const mockPages = [
  {
    path: 'semantic-seed-a1b2c3d4',
    title: '自分の性格について',
    page_type: 'concept',
    content:
      '自分の性格について:\n- いつも好奇心旺盛\n- 面白いものが大好き\n- 時々ぼんやりする',
    tags: ['seed', 'self_knowledge', 'personality', 'character:草十郎'],
    updated_at: '2026-06-15T10:30:00+00:00',
  },
  {
    path: 'episodic-seed-e5f6g7h8',
    title: '草十郎の記憶',
    page_type: 'entity',
    content:
      '私（草十郎）の記憶:\n役割: VTuber\n自分が誰で、どこから来たのか:\n元は天文学の研究者だった。',
    tags: ['seed', 'origin_story', 'identity', 'character:草十郎'],
    updated_at: '2026-06-15T10:30:00+00:00',
  },
  {
    path: 'raw-seed-i9j0k1l2',
    title: '会話の記憶',
    page_type: 'source',
    content: '会話の記憶:\n相手: こんにちは\n草十郎: やあ！今日はいい天気だね。',
    tags: ['seed', 'example_dialogue', 'example_0', 'character:草十郎'],
    updated_at: '2026-06-15T10:30:00+00:00',
  },
  {
    path: 'emergent-seed-m3n4o5p6',
    title: '綜合的な信念',
    page_type: 'synthesis',
    content:
      '自分の信念や大切にしている言葉:\n- 常に学び続ける\n- 丁寧に接する',
    tags: ['seed', 'core_beliefs', 'catchphrases', 'character:草十郎'],
    updated_at: '2026-06-15T10:30:00+00:00',
  },
]

const mockPagesWithRelations = [
  {
    ...mockPages[0],
    relations: [
      {
        source_id: 'semantic-seed-a1b2c3d4',
        target_id: 'episodic-seed-e5f6g7h8',
        relation_type: 'EXTENDS',
      },
      {
        source_id: 'semantic-seed-a1b2c3d4',
        target_id: 'raw-seed-i9j0k1l2',
        relation_type: 'DERIVES',
      },
    ],
  },
  {
    ...mockPages[1],
    relations: [
      {
        source_id: 'episodic-seed-e5f6g7h8',
        target_id: 'semantic-seed-a1b2c3d4',
        relation_type: 'EXTENDS',
      },
    ],
  },
  {
    ...mockPages[2],
    relations: [],
  },
  {
    ...mockPages[3],
    relations: [
      {
        source_id: 'emergent-seed-m3n4o5p6',
        target_id: 'semantic-seed-a1b2c3d4',
        relation_type: 'CONSOLIDATED_INTO',
      },
    ],
  },
]

// ── parseNodes ─────────────────────────────────────────────────────────

describe('parseNodes', () => {
  it('converts pages to MemoryNode array with correct ids', () => {
    const nodes = parseNodes(mockPages)

    expect(nodes).toHaveLength(4)
    expect(nodes.map((n) => n.id)).toEqual([
      'semantic-seed-a1b2c3d4',
      'episodic-seed-e5f6g7h8',
      'raw-seed-i9j0k1l2',
      'emergent-seed-m3n4o5p6',
    ])
  })

  it('uses title as label', () => {
    const nodes = parseNodes(mockPages)

    expect(nodes[0].label).toBe('自分の性格について')
    expect(nodes[1].label).toBe('草十郎の記憶')
  })

  it('falls back to content slice when title is empty', () => {
    const pages = [{ ...mockPages[0], title: '' }]
    const nodes = parseNodes(pages)

    expect(nodes[0].label).toBe(pages[0].content.slice(0, 50))
  })

  it('maps page_type to category correctly', () => {
    const nodes = parseNodes(mockPages)

    // concept → interest (via PAGE_TYPE_TO_CATEGORY) but overridden by personality tag → skill
    expect(nodes[0].category).toBe('skill')
    // entity → fact (via PAGE_TYPE_TO_CATEGORY) but overridden by identity tag → fact
    expect(nodes[1].category).toBe('fact')
    // source → other (via PAGE_TYPE_TO_CATEGORY)
    expect(nodes[2].category).toBe('other')
    // synthesis → relation (via PAGE_TYPE_TO_CATEGORY) but overridden by core_beliefs → knowledge
    expect(nodes[3].category).toBe('knowledge')
  })

  it('computes importance from tags', () => {
    const nodes = parseNodes(mockPages)

    // seed atoms get base 0.7 + content boost
    expect(nodes[0].importance).toBeGreaterThan(0.5)
    expect(nodes[0].importance).toBeLessThanOrEqual(1)

    // core_beliefs gets base 0.8
    expect(nodes[3].importance).toBeGreaterThan(nodes[2].importance)
  })

  it('uses salience when provided', () => {
    const pages = [{ ...mockPages[0], salience: 0.9 }]
    const nodes = parseNodes(pages)

    expect(nodes[0].importance).toBe(0.9)
  })

  it('clamps salience to [0, 1]', () => {
    const pagesHigh = [{ ...mockPages[0], salience: 1.5 }]
    const pagesLow = [{ ...mockPages[0], salience: -0.3 }]

    expect(parseNodes(pagesHigh)[0].importance).toBe(1)
    expect(parseNodes(pagesLow)[0].importance).toBe(0)
  })

  it('preserves content in metadata', () => {
    const nodes = parseNodes(mockPages)

    expect(nodes[0].content).toBe(mockPages[0].content)
    expect(nodes[0].metadata.page_type).toBe('concept')
    expect(nodes[0].metadata.tags).toEqual(mockPages[0].tags)
    expect(nodes[0].metadata.updated_at).toBe('2026-06-15T10:30:00+00:00')
  })

  it('returns empty array for empty input', () => {
    expect(parseNodes([])).toEqual([])
  })
})

// ── parseEdges ─────────────────────────────────────────────────────────

describe('parseEdges', () => {
  it('returns empty array when pages have no relations', () => {
    const edges = parseEdges(mockPages)
    expect(edges).toEqual([])
  })

  it('extracts relations from pages', () => {
    const edges = parseEdges(mockPagesWithRelations)

    expect(edges.length).toBeGreaterThan(0)
    expect(edges[0]).toHaveProperty('source')
    expect(edges[0]).toHaveProperty('target')
    expect(edges[0]).toHaveProperty('type')
    expect(edges[0]).toHaveProperty('weight')
    expect(edges[0]).toHaveProperty('label')
  })

  it('deduplicates bidirectional edges (A→B and B→A)', () => {
    // semantic-seed → episodic-seed (EXTENDS)
    // episodic-seed → semantic-seed (EXTENDS)  ← same undirected edge
    const edges = parseEdges(mockPagesWithRelations)

    const extendsEdges = edges.filter(
      (e) =>
        e.type === 'EXTENDS' &&
        ((e.source === 'semantic-seed-a1b2c3d4' &&
          e.target === 'episodic-seed-e5f6g7h8') ||
          (e.source === 'episodic-seed-e5f6g7h8' &&
            e.target === 'semantic-seed-a1b2c3d4')),
    )

    // Should be exactly 1 deduplicated edge, not 2
    expect(extendsEdges).toHaveLength(1)
  })

  it('preserves the first occurrence direction on dedup', () => {
    const edges = parseEdges(mockPagesWithRelations)
    const extendsEdge = edges.find(
      (e) =>
        e.type === 'EXTENDS' &&
        ((e.source === 'semantic-seed-a1b2c3d4' &&
          e.target === 'episodic-seed-e5f6g7h8') ||
          (e.source === 'episodic-seed-e5f6g7h8' &&
            e.target === 'semantic-seed-a1b2c3d4')),
    )

    // First page's relation is semantic→episodic
    expect(extendsEdge).toBeDefined()
    expect(extendsEdge!.source).toBe('semantic-seed-a1b2c3d4')
    expect(extendsEdge!.target).toBe('episodic-seed-e5f6g7h8')
  })

  it('skips self-referential relations', () => {
    const pages = [
      {
        ...mockPages[0],
        relations: [
          {
            source_id: 'semantic-seed-a1b2c3d4',
            target_id: 'semantic-seed-a1b2c3d4',
            relation_type: 'UPDATES',
          },
        ],
      },
    ]

    const edges = parseEdges(pages)
    expect(edges).toHaveLength(0)
  })

  it('generates human-readable labels', () => {
    const edges = parseEdges(mockPagesWithRelations)

    const extendsEdge = edges.find((e) => e.type === 'EXTENDS')
    expect(extendsEdge?.label).toBe('extends')

    const derivesEdge = edges.find((e) => e.type === 'DERIVES')
    expect(derivesEdge?.label).toBe('derives from')

    const consolidatedEdge = edges.find(
      (e) => e.type === 'CONSOLIDATED_INTO',
    )
    expect(consolidatedEdge?.label).toBe('consolidated into')
  })

  it('converts unknown relation types to lowercase with spaces', () => {
    const pages = [
      {
        ...mockPages[0],
        relations: [
          {
            source_id: 'a',
            target_id: 'b',
            relation_type: 'CUSTOM_TYPE',
          },
        ],
      },
    ]

    const edges = parseEdges(pages)
    expect(edges[0].label).toBe('custom type')
  })

  it('sets default weight to 0.5', () => {
    const edges = parseEdges(mockPagesWithRelations)

    for (const edge of edges) {
      expect(edge.weight).toBe(0.5)
    }
  })

  it('returns empty array for empty input', () => {
    expect(parseEdges([])).toEqual([])
  })
})

// ── parseMemoryGraph ───────────────────────────────────────────────────

describe('parseMemoryGraph', () => {
  it('combines nodes and edges from pages without relations', () => {
    const graph = parseMemoryGraph(mockPages)

    expect(graph.nodes).toHaveLength(4)
    expect(graph.edges).toHaveLength(0)
  })

  it('combines nodes and edges from pages with relations', () => {
    const graph = parseMemoryGraph(mockPagesWithRelations)

    expect(graph.nodes).toHaveLength(4)
    expect(graph.edges.length).toBeGreaterThan(0)
  })

  it('node ids match edge source/target references', () => {
    const graph = parseMemoryGraph(mockPagesWithRelations)
    const nodeIds = new Set(graph.nodes.map((n) => n.id))

    for (const edge of graph.edges) {
      expect(nodeIds.has(edge.source)).toBe(true)
      expect(nodeIds.has(edge.target)).toBe(true)
    }
  })
})

// ── Color constants ────────────────────────────────────────────────────

describe('CATEGORY_COLORS', () => {
  it('has colors for all expected categories', () => {
    const expected = [
      'skill',
      'interest',
      'fact',
      'relation',
      'knowledge',
      'preference',
      'other',
    ]
    for (const cat of expected) {
      expect(CATEGORY_COLORS[cat]).toBeDefined()
      expect(CATEGORY_COLORS[cat]).toMatch(/^var\(--/)
    }
  })
})

describe('RELATION_COLORS', () => {
  it('has colors for all backend relation types', () => {
    const backendTypes = [
      'UPDATES',
      'EXTENDS',
      'DERIVES',
      'EVOKES',
      'CONTRADICTS',
      'CONSOLIDATED_INTO',
    ]
    for (const type of backendTypes) {
      expect(RELATION_COLORS[type]).toBeDefined()
    }
  })

  it('has a default fallback color', () => {
    expect(RELATION_COLORS.default).toBeDefined()
  })
})

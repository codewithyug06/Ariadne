// Copyright 2026 The Ariadne Authors
// SPDX-License-Identifier: Apache-2.0

import { useEffect, useMemo, useRef, useState } from 'react';
import { drag as d3drag } from 'd3-drag';
import {
  forceCenter,
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  type Simulation,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from 'd3-force';
import { select } from 'd3-selection';
import { zoom as d3zoom, zoomIdentity } from 'd3-zoom';
import type { EdgeType, GraphEdge, GraphNode, NodeType, SessionGraph } from '../api/client';

const NODE_COLORS: Record<NodeType, string> = {
  user_request: '#58a6ff',
  tool_call: '#8b98a9',
  tool_result: '#56d4dd',
  sub_agent_invocation: '#bc8cff',
  memory_write: '#e3b341',
  final_output: '#3fb950',
  alert: '#f85149',
};

const ACTION_RING: Record<string, string> = {
  ALLOW: '#3fb950',
  WARN: '#d29922',
  ESCALATE: '#db6d28',
  BLOCK: '#f85149',
};

const EDGE_STYLES: Record<EdgeType, { stroke: string; dash: string; width: number }> = {
  caused_by: { stroke: '#4b5a72', dash: '', width: 1.5 },
  informed_by: { stroke: '#56d4dd', dash: '5 4', width: 1.5 },
  produces: { stroke: '#33415c', dash: '', width: 1.2 },
  calls: { stroke: '#bc8cff', dash: '2 3', width: 1.5 },
  contradicts: { stroke: '#f85149', dash: '', width: 2.2 },
  escalates_privilege: { stroke: '#bc8cff', dash: '', width: 2.2 },
};

const ROOT_CAUSE_COLOR = '#ff9f43';
const WIDTH = 760;
const HEIGHT = 520;

interface SimNode extends SimulationNodeDatum {
  id: string;
  node: GraphNode;
}

interface SimLink extends SimulationLinkDatum<SimNode> {
  id: string;
  edge: GraphEdge;
}

interface Props {
  graph: SessionGraph;
  blameChainIds?: string[];
}

function radius(node: GraphNode): number {
  if (node.node_type === 'user_request') return 12;
  if (node.node_type === 'alert') return 9;
  if (node.node_type === 'tool_result') return 6;
  return 8;
}

export function ProvenanceGraph({ graph, blameChainIds = [] }: Props) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const containerRef = useRef<SVGGElement | null>(null);
  const simulationRef = useRef<Simulation<SimNode, SimLink> | null>(null);
  const [selected, setSelected] = useState<GraphNode | null>(null);
  // The simulation mutates node coordinates in place, so a counter is the
  // re-render trigger; the value itself is never read.
  const [, setTick] = useState(0);

  const blameSet = useMemo(() => new Set(blameChainIds), [blameChainIds]);

  const { nodes, links } = useMemo(() => {
    const simNodes: SimNode[] = graph.nodes.map((node) => ({ id: node.id, node }));
    const byId = new Map(simNodes.map((entry) => [entry.id, entry]));
    const simLinks: SimLink[] = graph.edges
      .filter((edge) => byId.has(edge.source_id) && byId.has(edge.target_id))
      .map((edge) => ({
        id: edge.id,
        edge,
        source: byId.get(edge.source_id) as SimNode,
        target: byId.get(edge.target_id) as SimNode,
      }));
    return { nodes: simNodes, links: simLinks };
  }, [graph]);

  // The simulation mutates node positions in place; React re-renders on tick.
  useEffect(() => {
    if (nodes.length === 0) return;

    const simulation = forceSimulation<SimNode>(nodes)
      .force(
        'link',
        forceLink<SimNode, SimLink>(links)
          .id((entry) => entry.id)
          .distance(70)
          .strength(0.6),
      )
      .force('charge', forceManyBody().strength(-320))
      .force('center', forceCenter(WIDTH / 2, HEIGHT / 2))
      .force('collide', forceCollide<SimNode>().radius((entry) => radius(entry.node) + 8))
      .on('tick', () => setTick((value) => value + 1));

    simulationRef.current = simulation;
    return () => {
      simulation.stop();
      simulationRef.current = null;
    };
  }, [nodes, links]);

  useEffect(() => {
    if (!svgRef.current || !containerRef.current) return;
    const svg = select(svgRef.current);
    const container = select(containerRef.current);

    const zoomBehaviour = d3zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.2, 4])
      .on('zoom', (event) => container.attr('transform', event.transform.toString()));

    svg.call(zoomBehaviour);
    svg.call(zoomBehaviour.transform, zoomIdentity);
    return () => {
      svg.on('.zoom', null);
    };
  }, []);

  // Node dragging: pin while held, release on drop so the layout re-settles.
  //
  // The elements are rendered by React, so they carry no d3-bound datum. A
  // keyed `.data()` join would call its key function on those elements with an
  // undefined datum and throw, so each node is bound individually instead.
  useEffect(() => {
    const container = containerRef.current;
    const simulation = simulationRef.current;
    if (!container || !simulation) return;

    const behaviour = d3drag<SVGGElement, SimNode>()
      .on('start', (event, entry) => {
        if (!event.active) simulation.alphaTarget(0.3).restart();
        entry.fx = entry.x;
        entry.fy = entry.y;
      })
      .on('drag', (event, entry) => {
        entry.fx = event.x;
        entry.fy = event.y;
      })
      .on('end', (event, entry) => {
        if (!event.active) simulation.alphaTarget(0);
        entry.fx = null;
        entry.fy = null;
      });

    const elements = container.querySelectorAll<SVGGElement>('g.node');
    elements.forEach((element, index) => {
      const datum = nodes[index];
      if (datum) {
        select(element).datum(datum).call(behaviour);
      }
    });
  }, [nodes]);

  if (graph.nodes.length === 0) {
    return <div className="empty">No provenance recorded for this run.</div>;
  }

  return (
    <div className="graph-wrap">
      <svg ref={svgRef} viewBox={`0 0 ${WIDTH} ${HEIGHT}`} height={HEIGHT}>
        <defs>
          {Object.entries(EDGE_STYLES).map(([type, style]) => (
            <marker
              key={type}
              id={`arrow-${type}`}
              viewBox="0 -5 10 10"
              refX={20}
              refY={0}
              markerWidth={5}
              markerHeight={5}
              orient="auto"
            >
              <path d="M0,-5L10,0L0,5" fill={style.stroke} />
            </marker>
          ))}
        </defs>

        <g ref={containerRef}>
          {links.map((link) => {
            const source = link.source as SimNode;
            const target = link.target as SimNode;
            const style = EDGE_STYLES[link.edge.edge_type];
            return (
              <line
                key={link.id}
                x1={source.x ?? 0}
                y1={source.y ?? 0}
                x2={target.x ?? 0}
                y2={target.y ?? 0}
                stroke={style.stroke}
                strokeWidth={style.width}
                strokeDasharray={style.dash}
                markerEnd={`url(#arrow-${link.edge.edge_type})`}
                opacity={0.8}
              />
            );
          })}

          {nodes.map((entry) => {
            const { node } = entry;
            const isRootCause = node.id === graph.root_cause_node_id;
            const inBlameChain = blameSet.has(node.id);
            const ring = node.enforcement_action
              ? ACTION_RING[node.enforcement_action]
              : undefined;
            return (
              <g
                key={entry.id}
                className="node"
                transform={`translate(${entry.x ?? 0}, ${entry.y ?? 0})`}
                onClick={() => setSelected(node)}
                style={{ cursor: 'pointer' }}
              >
                {(isRootCause || inBlameChain) && (
                  <circle
                    r={radius(node) + 6}
                    fill="none"
                    stroke={ROOT_CAUSE_COLOR}
                    strokeWidth={isRootCause ? 3 : 1.5}
                    strokeDasharray={isRootCause ? '' : '3 3'}
                  />
                )}
                <circle
                  r={radius(node)}
                  fill={NODE_COLORS[node.node_type]}
                  stroke={ring ?? '#0b0f17'}
                  strokeWidth={ring ? 2.5 : 1}
                />
                <text
                  x={radius(node) + 6}
                  y={4}
                  fill="#e6edf3"
                  fontSize={10}
                  fontFamily="ui-monospace, monospace"
                  pointerEvents="none"
                >
                  {node.step_index > 0 ? `${node.step_index}. ` : ''}
                  {node.label.length > 28 ? `${node.label.slice(0, 27)}…` : node.label}
                </text>
              </g>
            );
          })}
        </g>
      </svg>

      {selected && <NodePanel node={selected} onClose={() => setSelected(null)} />}

      <div className="graph-legend">
        {Object.entries(NODE_COLORS).map(([type, color]) => (
          <span className="key" key={type}>
            <span className="swatch" style={{ background: color }} />
            {type.replace(/_/g, ' ')}
          </span>
        ))}
        {Object.entries(EDGE_STYLES).map(([type, style]) => (
          <span className="key" key={type}>
            <span
              className="line"
              style={{
                borderTopColor: style.stroke,
                borderTopStyle: style.dash ? 'dashed' : 'solid',
              }}
            />
            {type.replace(/_/g, ' ')}
          </span>
        ))}
        <span className="key">
          <span
            className="swatch"
            style={{ background: 'transparent', border: `2px solid ${ROOT_CAUSE_COLOR}` }}
          />
          root cause / blame chain
        </span>
      </div>
    </div>
  );
}

function NodePanel({ node, onClose }: { node: GraphNode; onClose: () => void }) {
  return (
    <div className="node-panel">
      <h3>
        <span style={{ color: NODE_COLORS[node.node_type] }}>●</span>
        {node.label}
        <button style={{ marginLeft: 'auto', padding: '0 6px' }} onClick={onClose}>
          ✕
        </button>
      </h3>
      <dl>
        <dt>type</dt>
        <dd>{node.node_type}</dd>
        <dt>step</dt>
        <dd>{node.step_index}</dd>
        {node.enforcement_action && (
          <>
            <dt>decision</dt>
            <dd style={{ color: ACTION_RING[node.enforcement_action] }}>
              {node.enforcement_action}
            </dd>
          </>
        )}
        {node.drift_score !== null && (
          <>
            <dt>drift</dt>
            <dd>{node.drift_score.toFixed(1)}</dd>
          </>
        )}
        <dt>time</dt>
        <dd>{new Date(node.timestamp).toLocaleTimeString()}</dd>
      </dl>
      <div style={{ color: '#8b98a9', fontSize: 11 }}>payload</div>
      <pre>{JSON.stringify(node.payload, null, 2)}</pre>
    </div>
  );
}

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
import { zoom as d3zoom, zoomIdentity, type ZoomBehavior } from 'd3-zoom';
import type { EdgeType, GraphEdge, GraphNode, NodeType, SessionGraph } from '../api/client';
import { CheckIcon, CopyIcon, MaximizeIcon, ZoomInIcon, ZoomOutIcon } from './Icons';

const NODE_COLORS: Record<NodeType, string> = {
  user_request: '#0284c7',
  tool_call: '#475569',
  tool_result: '#0d9488',
  sub_agent_invocation: '#7c3aed',
  memory_write: '#d97706',
  final_output: '#059669',
  alert: '#dc2626',
};

const ACTION_RING: Record<string, string> = {
  ALLOW: '#059669',
  WARN: '#d97706',
  ESCALATE: '#ea580c',
  BLOCK: '#dc2626',
};

const EDGE_STYLES: Record<EdgeType, { stroke: string; dash: string; width: number }> = {
  caused_by: { stroke: '#94a3b8', dash: '', width: 1.5 },
  informed_by: { stroke: '#0d9488', dash: '4 4', width: 1.5 },
  produces: { stroke: '#cbd5e1', dash: '', width: 1.2 },
  calls: { stroke: '#7c3aed', dash: '3 3', width: 1.5 },
  contradicts: { stroke: '#dc2626', dash: '', width: 2.2 },
  escalates_privilege: { stroke: '#ea580c', dash: '', width: 2.2 },
};

const ROOT_CAUSE_COLOR = '#e11d48';
const WIDTH = 760;
const HEIGHT = 500;

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
  if (node.node_type === 'user_request') return 13;
  if (node.node_type === 'alert') return 10;
  if (node.node_type === 'tool_result') return 7;
  return 9;
}

export function ProvenanceGraph({ graph, blameChainIds = [] }: Props) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const containerRef = useRef<SVGGElement | null>(null);
  const simulationRef = useRef<Simulation<SimNode, SimLink> | null>(null);
  const zoomBehaviorRef = useRef<ZoomBehavior<SVGSVGElement, unknown> | null>(null);
  const [selected, setSelected] = useState<GraphNode | null>(null);
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

  useEffect(() => {
    if (nodes.length === 0) return;

    const simulation = forceSimulation<SimNode>(nodes)
      .force(
        'link',
        forceLink<SimNode, SimLink>(links)
          .id((entry) => entry.id)
          .distance(75)
          .strength(0.6),
      )
      .force('charge', forceManyBody().strength(-340))
      .force('center', forceCenter(WIDTH / 2, HEIGHT / 2))
      .force('collide', forceCollide<SimNode>().radius((entry) => radius(entry.node) + 10))
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

    zoomBehaviorRef.current = zoomBehaviour;
    svg.call(zoomBehaviour);
    svg.call(zoomBehaviour.transform, zoomIdentity);
    return () => {
      svg.on('.zoom', null);
    };
  }, []);

  const handleZoom = (delta: number) => {
    if (!svgRef.current || !zoomBehaviorRef.current) return;
    const svg = select(svgRef.current);
    zoomBehaviorRef.current.scaleBy(svg, delta);
  };

  const handleResetZoom = () => {
    if (!svgRef.current || !zoomBehaviorRef.current) return;
    const svg = select(svgRef.current);
    zoomBehaviorRef.current.transform(svg, zoomIdentity);
  };

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
    return <div className="empty">No provenance graph recorded for this run.</div>;
  }

  return (
    <div className="graph-wrap">
      {/* Zoom Controls Overlay */}
      <div className="graph-controls">
        <button onClick={() => handleZoom(1.3)} title="Zoom in">
          <ZoomInIcon size={14} />
        </button>
        <button onClick={() => handleZoom(0.7)} title="Zoom out">
          <ZoomOutIcon size={14} />
        </button>
        <button onClick={handleResetZoom} title="Reset view">
          <MaximizeIcon size={14} />
        </button>
      </div>

      <svg ref={svgRef} viewBox={`0 0 ${WIDTH} ${HEIGHT}`} height={HEIGHT}>
        <defs>
          {Object.entries(EDGE_STYLES).map(([type, style]) => (
            <marker
              key={type}
              id={`arrow-${type}`}
              viewBox="0 -5 10 10"
              refX={22}
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
                    r={radius(node) + 7}
                    fill="none"
                    stroke={ROOT_CAUSE_COLOR}
                    strokeWidth={isRootCause ? 3 : 1.8}
                    strokeDasharray={isRootCause ? '' : '3 3'}
                  />
                )}
                <circle
                  r={radius(node)}
                  fill={NODE_COLORS[node.node_type]}
                  stroke={ring ?? '#ffffff'}
                  strokeWidth={ring ? 2.5 : 2}
                  style={{ filter: 'drop-shadow(0 1px 2px rgba(0,0,0,0.15))' }}
                />
                <text
                  x={radius(node) + 7}
                  y={4}
                  fill="#0f172a"
                  fontSize={11}
                  fontWeight={600}
                  fontFamily="var(--mono)"
                  pointerEvents="none"
                  style={{ textShadow: '0 1px 2px rgba(255,255,255,0.9)' }}
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
          Root cause / Blame
        </span>
      </div>
    </div>
  );
}

function NodePanel({ node, onClose }: { node: GraphNode; onClose: () => void }) {
  const [copied, setCopied] = useState(false);

  const copyPayload = () => {
    navigator.clipboard.writeText(JSON.stringify(node.payload, null, 2));
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="node-panel">
      <h3>
        <span style={{ color: NODE_COLORS[node.node_type] }}>●</span>
        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {node.label}
        </span>
        <button style={{ marginLeft: 'auto', padding: '2px 6px' }} onClick={onClose}>
          ✕
        </button>
      </h3>
      <dl>
        <dt>Node Type</dt>
        <dd>{node.node_type}</dd>
        <dt>Step</dt>
        <dd>{node.step_index}</dd>
        {node.enforcement_action && (
          <>
            <dt>Decision</dt>
            <dd style={{ color: ACTION_RING[node.enforcement_action], fontWeight: 700 }}>
              {node.enforcement_action}
            </dd>
          </>
        )}
        {node.drift_score !== null && (
          <>
            <dt>Drift</dt>
            <dd>{node.drift_score.toFixed(1)}</dd>
          </>
        )}
        <dt>Time</dt>
        <dd>{new Date(node.timestamp).toLocaleTimeString()}</dd>
      </dl>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 8 }}>
        <span style={{ color: 'var(--text-dim)', fontSize: 11, textTransform: 'uppercase' }}>Payload</span>
        <button className="copy-btn" onClick={copyPayload} title="Copy payload JSON">
          {copied ? <CheckIcon size={12} style={{ color: 'var(--allow)' }} /> : <CopyIcon size={12} />}
        </button>
      </div>
      <pre>{JSON.stringify(node.payload, null, 2)}</pre>
    </div>
  );
}

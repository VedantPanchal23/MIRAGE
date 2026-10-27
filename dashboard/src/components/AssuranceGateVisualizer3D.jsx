import React, { useRef, useEffect, useState } from "react";
import { Shield, CheckCircle2, AlertTriangle, Eye, ArrowRight } from "lucide-react";

export function AssuranceGateVisualizer3D({ currentStage = 0, isEvaluating = false }) {
  const canvasRef = useRef(null);
  const [selectedGate, setSelectedGate] = useState(null);
  const [hoveredGate, setHoveredGate] = useState(null);

  const gates = [
    {
      id: 1,
      name: "Gate 1: Input Assurance",
      subtitle: "Identity, Tenant Attribution & Prompt Shield",
      metric: "< 4ms",
      status: "PASS",
      description: "Cryptographic tenant binding, role-based capability verification, fail-closed injection defense, and budget pre-flight check.",
      color: "#0071e3",
    },
    {
      id: 2,
      name: "Gate 2: Context Assurance",
      subtitle: "RAG Provenance & Memory Governance",
      metric: "0.98 Reciprocal Rank",
      status: "PASS",
      description: "Qdrant vector similarity provenance, freshness validation, poisoning defense, and contextual isolation under PostgreSQL RLS.",
      color: "#34c759",
    },
    {
      id: 3,
      name: "Gate 3: Action Assurance",
      subtitle: "Capability Fencing & HITL Approval",
      metric: "Zero Stale Leases",
      status: "ACTIVE",
      description: "Blast-radius containment, distributed lease fencing, two-phase commit, and human-in-the-loop approval escalation.",
      color: "#ff9500",
    },
    {
      id: 4,
      name: "Gate 4: Output Assurance",
      subtitle: "Factual Verification & Hallucination Risk (HRS)",
      metric: "HRS: 0.12 (LOW RISK)",
      status: "PASS",
      description: "Syntactic JSON validation, claim extraction, NLI cross-encoder entailment, semantic consistency (SCS), and TreeSHAP attribution.",
      color: "#af52de",
    },
    {
      id: 5,
      name: "Gate 5: Outcome Assurance",
      subtitle: "Independent Reality Verification",
      metric: "Epistemic Independence",
      status: "PASS",
      description: "External target verification confirming actual real-world state transitions against predicted postconditions, backed by SHA-256 Merkle audit.",
      color: "#0071e3",
    },
  ];

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let animationFrameId;
    let angle = 0;
    let mouseX = 0;
    let mouseY = 0;

    // Handle high-DPI displays
    const dpr = window.devicePixelRatio || 1;
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    ctx.scale(dpr, dpr);

    // Particle nodes for orbital rings
    const particles = [];
    for (let i = 0; i < 48; i++) {
      particles.push({
        orbitRadius: 40 + Math.random() * 120,
        theta: Math.random() * Math.PI * 2,
        speed: (Math.random() * 0.008 + 0.004) * (Math.random() > 0.5 ? 1 : -1),
        size: Math.random() * 2 + 1,
        alpha: Math.random() * 0.5 + 0.2,
      });
    }

    const render = () => {
      ctx.clearRect(0, 0, width, height);

      const centerX = width / 2;
      const centerY = height / 2;
      angle += isEvaluating ? 0.025 : 0.008;

      // Draw faint background grid
      ctx.strokeStyle = "rgba(0, 0, 0, 0.03)";
      ctx.lineWidth = 1;
      const gridSize = 30;
      for (let x = 0; x < width; x += gridSize) {
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, height);
        ctx.stroke();
      }
      for (let y = 0; y < height; y += gridSize) {
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(width, y);
        ctx.stroke();
      }

      // Draw Central Core (The Model/Agent Kernel)
      const corePulse = 18 + Math.sin(angle * 2) * 2;
      const grad = ctx.createRadialGradient(centerX, centerY, 0, centerX, centerY, corePulse * 1.8);
      grad.addColorStop(0, "rgba(0, 113, 227, 0.9)");
      grad.addColorStop(0.6, "rgba(0, 113, 227, 0.2)");
      grad.addColorStop(1, "rgba(0, 113, 227, 0)");

      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.arc(centerX, centerY, corePulse * 2, 0, Math.PI * 2);
      ctx.fill();

      ctx.fillStyle = "#ffffff";
      ctx.beginPath();
      ctx.arc(centerX, centerY, 8, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = "#0071e3";
      ctx.lineWidth = 2;
      ctx.stroke();

      // Draw 5 3D Orbital Rings (Perspective Ellipses)
      const ringRadii = [55, 85, 115, 145, 175];
      const colors = ["#0071e3", "#34c759", "#ff9500", "#af52de", "#0071e3"];

      ringRadii.forEach((r, idx) => {
        const isCurrent = currentStage === idx + 1 || (currentStage === 0 && isEvaluating);
        ctx.save();
        ctx.translate(centerX, centerY);
        ctx.rotate(0.25); // Slight tilt for 3D look

        // Ring stroke
        ctx.beginPath();
        ctx.ellipse(0, 0, r, r * 0.45, 0, 0, Math.PI * 2);
        ctx.strokeStyle = isCurrent ? colors[idx] : "rgba(0, 0, 0, 0.08)";
        ctx.lineWidth = isCurrent ? 2 : 1;
        if (isCurrent) {
          ctx.setLineDash([4, 4]);
        }
        ctx.stroke();
        ctx.setLineDash([]);

        // Orbital Gate Beacon Node
        const nodeAngle = angle * (idx % 2 === 0 ? 1 : -0.8) + (idx * Math.PI) / 2.5;
        const nodeX = Math.cos(nodeAngle) * r;
        const nodeY = Math.sin(nodeAngle) * (r * 0.45);

        // Glow behind node
        const nodeGrad = ctx.createRadialGradient(nodeX, nodeY, 0, nodeX, nodeY, 14);
        nodeGrad.addColorStop(0, colors[idx]);
        nodeGrad.addColorStop(1, "rgba(255, 255, 255, 0)");
        ctx.fillStyle = nodeGrad;
        ctx.beginPath();
        ctx.arc(nodeX, nodeY, 14, 0, Math.PI * 2);
        ctx.fill();

        // Node center
        ctx.fillStyle = isCurrent ? "#ffffff" : colors[idx];
        ctx.beginPath();
        ctx.arc(nodeX, nodeY, 5, 0, Math.PI * 2);
        ctx.fill();
        ctx.strokeStyle = colors[idx];
        ctx.lineWidth = 2;
        ctx.stroke();

        ctx.restore();
      });

      // Render floating particles along orbits
      particles.forEach((p) => {
        p.theta += p.speed;
        const px = centerX + Math.cos(p.theta) * p.orbitRadius;
        const py = centerY + Math.sin(p.theta) * (p.orbitRadius * 0.45);

        ctx.fillStyle = `rgba(0, 113, 227, ${p.alpha})`;
        ctx.beginPath();
        ctx.arc(px, py, p.size, 0, Math.PI * 2);
        ctx.fill();
      });

      animationFrameId = requestAnimationFrame(render);
    };

    render();

    return () => {
      cancelAnimationFrame(animationFrameId);
    };
  }, [currentStage, isEvaluating]);

  return (
    <div className="bg-apple-surface rounded-3xl p-6 border border-apple-border shadow-apple-card">
      <div className="flex flex-col lg:flex-row items-start lg:items-center justify-between gap-4 pb-6 border-b border-apple-border">
        <div>
          <div className="flex items-center space-x-2">
            <span className="w-2.5 h-2.5 rounded-full bg-apple-blue animate-ping" />
            <h2 className="text-xl font-bold text-apple-text tracking-tight">
              Five Assurance Gates Visualizer
            </h2>
          </div>
          <p className="text-sm text-apple-secondary mt-1">
            Real-time multi-dimensional assurance pipeline controlling every consequential model interaction.
          </p>
        </div>

        <div className="flex items-center space-x-2 text-xs font-medium">
          <div className="flex items-center space-x-1.5 px-3 py-1.5 rounded-full bg-apple-subtle border border-apple-border text-apple-secondary">
            <span className="w-2 h-2 rounded-full bg-apple-green" />
            <span>Epistemic Fencing Active</span>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 mt-6 items-center">
        {/* 3D Canvas Projection */}
        <div className="lg:col-span-6 relative flex items-center justify-center min-h-[300px] sm:min-h-[340px] bg-apple-subtle/40 rounded-2xl border border-apple-border/70 overflow-hidden">
          <canvas
            ref={canvasRef}
            className="w-full h-full cursor-pointer"
            style={{ minHeight: "340px" }}
          />

          <div className="absolute bottom-3 left-3 text-[11px] font-mono text-apple-secondary bg-white/90 backdrop-blur-sm px-2.5 py-1 rounded-md border border-apple-border shadow-apple-sm">
            Core: Allam-2 / Llama 3.3 • 60 FPS
          </div>
        </div>

        {/* Interactive Gate Cards */}
        <div className="lg:col-span-6 space-y-2.5">
          {gates.map((gate) => {
            const isSelected = selectedGate === gate.id;
            const isHovered = hoveredGate === gate.id;

            return (
              <div
                key={gate.id}
                onClick={() => setSelectedGate(isSelected ? null : gate.id)}
                onMouseEnter={() => setHoveredGate(gate.id)}
                onMouseLeave={() => setHoveredGate(null)}
                className={`p-3.5 rounded-2xl border transition-all cursor-pointer ${
                  isSelected
                    ? "bg-apple-subtle/80 border-apple-blue shadow-apple-sm"
                    : isHovered
                    ? "bg-apple-subtle/50 border-apple-borderStrong"
                    : "bg-apple-surface border-apple-border hover:bg-apple-subtle/30"
                }`}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center space-x-2.5">
                    <span
                      className="w-2.5 h-2.5 rounded-full"
                      style={{ backgroundColor: gate.color }}
                    />
                    <div>
                      <div className="font-semibold text-xs sm:text-sm text-apple-text">
                        {gate.name}
                      </div>
                      <div className="text-[11px] text-apple-secondary">{gate.subtitle}</div>
                    </div>
                  </div>

                  <div className="flex items-center space-x-2">
                    <span className="text-[11px] font-mono font-medium px-2 py-0.5 rounded-full bg-apple-subtle text-apple-secondary border border-apple-border">
                      {gate.metric}
                    </span>
                    <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-apple-green/10 text-apple-green border border-apple-green/20">
                      {gate.status}
                    </span>
                  </div>
                </div>

                {isSelected && (
                  <div className="mt-3 pt-3 border-t border-apple-border/70 text-xs text-apple-secondary leading-relaxed">
                    <p>{gate.description}</p>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

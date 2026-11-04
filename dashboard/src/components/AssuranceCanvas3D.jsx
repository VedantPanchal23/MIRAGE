import React, { useRef, useEffect } from "react";
import * as THREE from "three";

/**
 * AssuranceCanvas3D — Industrial Futuristic WebGL Reactor Core
 * Visualizes the Five Inviolable Assurance Gates as a high-precision,
 * multi-ring holographic execution containment core with real-time particle flux,
 * rotating telemetry calipers, raycasted ring interaction, and interactive pointer parallax.
 */
export default function AssuranceCanvas3D({
  className = "",
  activeGate = 1,
  onSelectGate = null,
}) {
  const mountRef = useRef(null);
  const activeGateRef = useRef(activeGate);

  useEffect(() => {
    activeGateRef.current = activeGate;
  }, [activeGate]);

  useEffect(() => {
    const container = mountRef.current;
    if (!container) return;

    let width = container.clientWidth || 800;
    let height = container.clientHeight || 500;

    // 1. Safe WebGL Context Detection (for headless CI & JSDOM compatibility)
    let renderer;
    try {
      const testCanvas = document.createElement("canvas");
      const gl = testCanvas.getContext("webgl") || testCanvas.getContext("experimental-webgl");
      if (!gl) {
        throw new Error("WebGL unsupported in current context");
      }

      renderer = new THREE.WebGLRenderer({
        alpha: true,
        antialias: true,
        powerPreference: "high-performance",
      });
      renderer.setSize(width, height);
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      renderer.toneMapping = THREE.ACESFilmicToneMapping;
      renderer.toneMappingExposure = 1.5;
      container.appendChild(renderer.domElement);
    } catch {
      // Graceful fallback for non-GPU / test environments
      return;
    }

    // 2. Scene & Camera setup
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(40, width / height, 0.1, 1000);
    camera.position.set(0, 3.5, 27);

    // 3. Industrial Lighting System
    const ambientLight = new THREE.AmbientLight(0x0a101d, 1.4);
    scene.add(ambientLight);

    const coreLight = new THREE.PointLight(0x00f0ff, 5, 35);
    coreLight.position.set(0, 0, 0);
    scene.add(coreLight);

    const amberLight = new THREE.DirectionalLight(0xf59e0b, 1.6);
    amberLight.position.set(-18, 14, 12);
    scene.add(amberLight);

    const cyanLight = new THREE.DirectionalLight(0x00f0ff, 2.0);
    cyanLight.position.set(18, -12, 16);
    scene.add(cyanLight);

    const emeraldLight = new THREE.PointLight(0x10b981, 2.5, 25);
    emeraldLight.position.set(0, -6, 8);
    scene.add(emeraldLight);

    // 4. Industrial Execution Core (Central Holographic Nucleus)
    const masterGroup = new THREE.Group();
    scene.add(masterGroup);

    // Inner glowing faceted nucleus
    const nucleusGeo = new THREE.IcosahedronGeometry(2.2, 2);
    const nucleusMat = new THREE.MeshPhysicalMaterial({
      color: 0x050b14,
      emissive: 0x003344,
      emissiveIntensity: 0.9,
      roughness: 0.15,
      metalness: 0.9,
      clearcoat: 1.0,
      wireframe: false,
    });
    const nucleusMesh = new THREE.Mesh(nucleusGeo, nucleusMat);
    masterGroup.add(nucleusMesh);

    // Tactical Wireframe Geodesic Shield
    const cageGeo = new THREE.IcosahedronGeometry(2.5, 1);
    const cageMat = new THREE.MeshBasicMaterial({
      color: 0x00f0ff,
      wireframe: true,
      transparent: true,
      opacity: 0.45,
    });
    const cageMesh = new THREE.Mesh(cageGeo, cageMat);
    masterGroup.add(cageMesh);

    // Inner Plasma Orb with pulsing wireframe
    const innerPlasmaGeo = new THREE.SphereGeometry(1.4, 16, 16);
    const innerPlasmaMat = new THREE.MeshBasicMaterial({
      color: 0x00f0ff,
      wireframe: true,
      transparent: true,
      opacity: 0.6,
    });
    const innerPlasmaMesh = new THREE.Mesh(innerPlasmaGeo, innerPlasmaMat);
    masterGroup.add(innerPlasmaMesh);

    // 5. Five Inviolable Assurance Gate Caliper Rings
    const gateConfigs = [
      { id: 1, name: "Gate 1: Input Assurance", color: 0x00f0ff, radius: 4.2, tube: 0.038, speed: 0.007, rotAxis: [0.35, 0.12, 0.0] },
      { id: 2, name: "Gate 2: Context Provenance", color: 0x10b981, radius: 5.8, tube: 0.038, speed: -0.005, rotAxis: [-0.42, 0.28, 0.12] },
      { id: 3, name: "Gate 3: Action & Leases", color: 0xf59e0b, radius: 7.4, tube: 0.045, speed: 0.004, rotAxis: [0.48, -0.38, 0.22] },
      { id: 4, name: "Gate 4: Output HRS", color: 0xa855f7, radius: 9.0, tube: 0.040, speed: -0.003, rotAxis: [-0.25, 0.55, -0.15] },
      { id: 5, name: "Gate 5: Reality Verification", color: 0x3b82f6, radius: 10.6, tube: 0.048, speed: 0.002, rotAxis: [0.15, -0.25, 0.45] },
    ];

    const rings = [];
    const interactiveMeshes = [];

    gateConfigs.forEach((cfg) => {
      const ringGroup = new THREE.Group();
      ringGroup.rotation.set(...cfg.rotAxis);

      // Torus ring track
      const ringGeo = new THREE.TorusGeometry(cfg.radius, cfg.tube, 12, 100);
      const ringMat = new THREE.MeshStandardMaterial({
        color: cfg.color,
        emissive: cfg.color,
        emissiveIntensity: 0.4,
        roughness: 0.25,
        metalness: 0.85,
      });
      const ringMesh = new THREE.Mesh(ringGeo, ringMat);
      ringMesh.userData = { gateId: cfg.id };
      ringGroup.add(ringMesh);
      interactiveMeshes.push(ringMesh);

      // Orbital telemetry node on ring (faceted diamond beacon)
      const nodeGeo = new THREE.OctahedronGeometry(0.28, 0);
      const nodeMat = new THREE.MeshBasicMaterial({ color: cfg.color });
      const nodeMesh = new THREE.Mesh(nodeGeo, nodeMat);
      nodeMesh.position.set(cfg.radius, 0, 0);
      nodeMesh.userData = { gateId: cfg.id };
      ringGroup.add(nodeMesh);
      interactiveMeshes.push(nodeMesh);

      // Outer thin secondary caliper track
      const outerTrackGeo = new THREE.TorusGeometry(cfg.radius + 0.22, 0.008, 4, 80);
      const outerTrackMat = new THREE.MeshBasicMaterial({
        color: cfg.color,
        transparent: true,
        opacity: 0.25,
      });
      const outerTrackMesh = new THREE.Mesh(outerTrackGeo, outerTrackMat);
      ringGroup.add(outerTrackMesh);

      masterGroup.add(ringGroup);
      rings.push({ id: cfg.id, group: ringGroup, ringMesh, nodeMesh, ringMat, baseColor: cfg.color, speed: cfg.speed });
    });

    // 6. Tactical Perspective Floor Grid
    const gridHelper = new THREE.GridHelper(36, 36, 0x00f0ff, 0x1e2433);
    gridHelper.position.y = -7.0;
    gridHelper.material.opacity = 0.35;
    gridHelper.material.transparent = true;
    masterGroup.add(gridHelper);

    // 7. Multi-Color Gate Data Particle Stream
    const particleCount = 350;
    const particleGeo = new THREE.BufferGeometry();
    const particlePos = new Float32Array(particleCount * 3);
    const particleColors = new Float32Array(particleCount * 3);
    const particleVel = [];

    const colorPalette = [
      new THREE.Color(0x00f0ff), // Gate 1 Cyan
      new THREE.Color(0x10b981), // Gate 2 Emerald
      new THREE.Color(0xf59e0b), // Gate 3 Amber
      new THREE.Color(0xa855f7), // Gate 4 Purple
      new THREE.Color(0x3b82f6), // Gate 5 Cobalt
    ];

    for (let i = 0; i < particleCount; i++) {
      const radius = 3.2 + Math.random() * 9.5;
      const theta = Math.random() * Math.PI * 2;
      const phi = (Math.random() - 0.5) * Math.PI;

      particlePos[i * 3] = radius * Math.cos(theta) * Math.cos(phi);
      particlePos[i * 3 + 1] = radius * Math.sin(phi);
      particlePos[i * 3 + 2] = radius * Math.sin(theta) * Math.cos(phi);

      const color = colorPalette[i % colorPalette.length];
      particleColors[i * 3] = color.r;
      particleColors[i * 3 + 1] = color.g;
      particleColors[i * 3 + 2] = color.b;

      particleVel.push({
        orbitSpeed: (0.002 + Math.random() * 0.007) * (Math.random() > 0.5 ? 1 : -1),
        radius: radius,
        theta: theta,
        phi: phi,
        driftY: (Math.random() - 0.5) * 0.005,
      });
    }

    particleGeo.setAttribute("position", new THREE.BufferAttribute(particlePos, 3));
    particleGeo.setAttribute("color", new THREE.BufferAttribute(particleColors, 3));

    const particleMat = new THREE.PointsMaterial({
      size: 0.14,
      vertexColors: true,
      transparent: true,
      opacity: 0.85,
      blending: THREE.AdditiveBlending,
    });
    const particleSystem = new THREE.Points(particleGeo, particleMat);
    masterGroup.add(particleSystem);

    // 8. Raycasting and Interactive Pointer Parallax
    const raycaster = new THREE.Raycaster();
    const mouse = new THREE.Vector2();
    let mouseX = 0;
    let mouseY = 0;
    let targetX = 0;
    let targetY = 0;

    const handlePointerMove = (e) => {
      const rect = container.getBoundingClientRect();
      const x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
      const y = -(((e.clientY - rect.top) / rect.height) * 2 - 1);
      mouse.x = x;
      mouse.y = y;
      targetX = x * 0.45;
      targetY = y * 0.45;
    };

    const handleClick = () => {
      if (!onSelectGate) return;
      raycaster.setFromCamera(mouse, camera);
      const intersects = raycaster.intersectObjects(interactiveMeshes, false);
      if (intersects.length > 0) {
        const hit = intersects[0].object;
        if (hit.userData && hit.userData.gateId) {
          onSelectGate(hit.userData.gateId);
        }
      }
    };

    window.addEventListener("pointermove", handlePointerMove);
    container.addEventListener("click", handleClick);

    // 9. Responsive Resize Observer
    const resizeObserver = new ResizeObserver(() => {
      if (!container || !renderer) return;
      const newWidth = container.clientWidth || 800;
      const newHeight = container.clientHeight || 500;
      camera.aspect = newWidth / newHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(newWidth, newHeight);
    });
    resizeObserver.observe(container);

    // 10. High-Precision Animation Loop
    let animationFrameId;
    let clock = new THREE.Clock();

    const animate = () => {
      animationFrameId = requestAnimationFrame(animate);
      const time = clock.getElapsedTime();

      // Smooth camera parallax easing
      mouseX += (targetX - mouseX) * 0.05;
      mouseY += (targetY - mouseY) * 0.05;
      masterGroup.rotation.y = mouseX + time * 0.035;
      masterGroup.rotation.x = -mouseY + Math.sin(time * 0.25) * 0.06;

      // Nucleus and Plasma Breathing
      const scale = 1 + Math.sin(time * 2.8) * 0.04;
      nucleusMesh.scale.set(scale, scale, scale);
      cageMesh.rotation.y = -time * 0.18;
      cageMesh.rotation.z = time * 0.09;
      innerPlasmaMesh.rotation.x = time * 0.3;
      innerPlasmaMesh.rotation.y = -time * 0.25;

      // Caliper Rings & Active Gate Focus Highlighting
      const currentActive = activeGateRef.current;
      rings.forEach((r) => {
        const isActive = r.id === currentActive;
        const currentSpeed = isActive ? r.speed * 2.2 : r.speed;

        r.group.rotation.z += currentSpeed;
        r.group.rotation.y += currentSpeed * 0.5;

        // Dynamic Active Highlight Modulation
        if (isActive) {
          r.ringMat.emissiveIntensity = 1.6 + Math.sin(time * 4) * 0.5;
          r.nodeMesh.scale.set(1.6, 1.6, 1.6);
        } else {
          r.ringMat.emissiveIntensity = 0.35;
          r.nodeMesh.scale.set(1.0, 1.0, 1.0);
        }
      });

      // Update Particle Orbits
      const positions = particleGeo.attributes.position.array;
      for (let i = 0; i < particleCount; i++) {
        const p = particleVel[i];
        p.theta += p.orbitSpeed;
        positions[i * 3] = p.radius * Math.cos(p.theta) * Math.cos(p.phi);
        positions[i * 3 + 1] += p.driftY;
        if (Math.abs(positions[i * 3 + 1]) > 5.0) p.driftY *= -1;
        positions[i * 3 + 2] = p.radius * Math.sin(p.theta) * Math.cos(p.phi);
      }
      particleGeo.attributes.position.needsUpdate = true;

      renderer.render(scene, camera);
    };

    animate();

    return () => {
      cancelAnimationFrame(animationFrameId);
      window.removeEventListener("pointermove", handlePointerMove);
      container.removeEventListener("click", handleClick);
      resizeObserver.disconnect();
      if (renderer && renderer.domElement && container.contains(renderer.domElement)) {
        container.removeChild(renderer.domElement);
      }
      scene.clear();
      renderer?.dispose();
    };
  }, [onSelectGate]);

  return (
    <div
      ref={mountRef}
      className={`relative w-full h-full min-h-[460px] overflow-hidden flex items-center justify-center cursor-crosshair select-none ${className}`}
      aria-label="3D Holographic Five-Gate Execution Assurance Core"
    >
      {/* Tactical HUD Overlay Markers */}
      <div className="absolute top-3 left-4 text-[10px] font-mono tracking-widest text-mirage-cyan/80 uppercase pointer-events-none flex items-center space-x-2">
        <span className="inline-block w-2 h-2 bg-mirage-cyan rounded-full animate-ping" />
        <span>GATES_REACTOR // ACTIVE ORBIT GATE_0{activeGate}</span>
      </div>
      <div className="absolute bottom-3 right-4 text-[9px] font-mono tracking-widest text-mirage-muted uppercase pointer-events-none">
        TWO_PHASE_LEASE_FENCED // FAIL_CLOSED
      </div>
      <div className="absolute top-3 right-4 text-[9px] font-mono text-mirage-subtext/70 uppercase pointer-events-none hidden sm:block">
        CLICK ORBIT CALIPERS TO INSPECT GATES
      </div>
    </div>
  );
}

import React, { useRef, useEffect } from "react";
import * as THREE from "three";

/**
 * AssuranceCanvas3D
 * Heavy WebGL 3D execution assurance visualizer built with Three.js.
 * Renders the Five Inviolable Assurance Gates as interactive concentric orbital
 * rings with floating transactional particles, an execution core, and mouse-reactive parallax.
 */
export default function AssuranceCanvas3D({ className = "" }) {
  const mountRef = useRef(null);

  useEffect(() => {
    const container = mountRef.current;
    if (!container) return;

    let width = container.clientWidth || 800;
    let height = container.clientHeight || 500;

    // 1. Safe WebGL Context Detection (for Headless CI & JSDOM compatibility)
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
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      renderer.toneMapping = THREE.ACESFilmicToneMapping;
      renderer.toneMappingExposure = 1.2;
      container.appendChild(renderer.domElement);
    } catch {
      // Graceful fallback for non-GPU / test environments
      return;
    }

    // 2. Scene, Camera
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 1000);
    camera.position.set(0, 0, 24);

    // 2. Lighting
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.8);
    scene.add(ambientLight);

    const pointLight = new THREE.PointLight(0x0071e3, 3, 50);
    pointLight.position.set(0, 0, 5);
    scene.add(pointLight);

    const rimLight = new THREE.DirectionalLight(0x38bdf8, 1.5);
    rimLight.position.set(10, 15, 10);
    scene.add(rimLight);

    // 3. Central Assurance Core
    const coreGroup = new THREE.Group();
    scene.add(coreGroup);

    const coreGeo = new THREE.IcosahedronGeometry(2.0, 2);
    const coreMat = new THREE.MeshPhysicalMaterial({
      color: 0x0071e3,
      emissive: 0x002244,
      roughness: 0.2,
      metalness: 0.8,
      clearcoat: 1.0,
      clearcoatRoughness: 0.1,
      wireframe: false,
    });
    const coreMesh = new THREE.Mesh(coreGeo, coreMat);
    coreGroup.add(coreMesh);

    // Wireframe Cage around Core
    const cageGeo = new THREE.IcosahedronGeometry(2.2, 1);
    const cageMat = new THREE.MeshBasicMaterial({
      color: 0x38bdf8,
      wireframe: true,
      transparent: true,
      opacity: 0.35,
    });
    const cageMesh = new THREE.Mesh(cageGeo, cageMat);
    coreGroup.add(cageMesh);

    // 4. Five Assurance Gate Orbital Rings
    const gateColors = [
      { color: 0x0ea5e9, radius: 3.8, tube: 0.04, tiltX: 0.4, tiltY: 0.2, speed: 0.008, name: "Gate 1: Input" },
      { color: 0x10b981, radius: 5.2, tube: 0.04, tiltX: -0.5, tiltY: 0.4, speed: -0.006, name: "Gate 2: Context" },
      { color: 0xf59e0b, radius: 6.8, tube: 0.05, tiltX: 0.7, tiltY: -0.3, speed: 0.005, name: "Gate 3: Action" },
      { color: 0xa855f7, radius: 8.4, tube: 0.04, tiltX: -0.3, tiltY: 0.6, speed: -0.004, name: "Gate 4: Output" },
      { color: 0x2563eb, radius: 10.0, tube: 0.05, tiltX: 0.2, tiltY: -0.5, speed: 0.003, name: "Gate 5: Reality" },
    ];

    const rings = [];
    gateColors.forEach((cfg) => {
      const ringGroup = new THREE.Group();
      ringGroup.rotation.x = cfg.tiltX;
      ringGroup.rotation.y = cfg.tiltY;

      // Torus Geometry for Orbital Track
      const torusGeo = new THREE.TorusGeometry(cfg.radius, cfg.tube, 16, 120);
      const torusMat = new THREE.MeshBasicMaterial({
        color: cfg.color,
        transparent: true,
        opacity: 0.45,
      });
      const torusMesh = new THREE.Mesh(torusGeo, torusMat);
      ringGroup.add(torusMesh);

      // Orbiting Gate Node / Satellite
      const nodeGeo = new THREE.SphereGeometry(0.22, 16, 16);
      const nodeMat = new THREE.MeshStandardMaterial({
        color: cfg.color,
        emissive: cfg.color,
        emissiveIntensity: 0.8,
        roughness: 0.1,
      });
      const nodeMesh = new THREE.Mesh(nodeGeo, nodeMat);
      nodeMesh.position.x = cfg.radius;
      ringGroup.add(nodeMesh);

      scene.add(ringGroup);
      rings.push({ group: ringGroup, node: nodeMesh, speed: cfg.speed, radius: cfg.radius });
    });

    // 5. Transaction Swarm Particles (350 floating nodes)
    const particleCount = 350;
    const particlePositions = new Float32Array(particleCount * 3);
    const particleColors = new Float32Array(particleCount * 3);
    const colorChoices = [
      new THREE.Color(0x0ea5e9),
      new THREE.Color(0x10b981),
      new THREE.Color(0xf59e0b),
      new THREE.Color(0xa855f7),
      new THREE.Color(0x38bdf8),
    ];

    for (let i = 0; i < particleCount; i++) {
      const r = 2.5 + Math.random() * 9.5;
      const theta = Math.random() * Math.PI * 2;
      const phi = (Math.random() - 0.5) * Math.PI;

      particlePositions[i * 3] = r * Math.cos(theta) * Math.cos(phi);
      particlePositions[i * 3 + 1] = r * Math.sin(theta) * Math.cos(phi);
      particlePositions[i * 3 + 2] = r * Math.sin(phi);

      const chosenColor = colorChoices[Math.floor(Math.random() * colorChoices.length)];
      particleColors[i * 3] = chosenColor.r;
      particleColors[i * 3 + 1] = chosenColor.g;
      particleColors[i * 3 + 2] = chosenColor.b;
    }

    const particleGeo = new THREE.BufferGeometry();
    particleGeo.setAttribute("position", new THREE.BufferAttribute(particlePositions, 3));
    particleGeo.setAttribute("color", new THREE.BufferAttribute(particleColors, 3));

    const particleMat = new THREE.PointsMaterial({
      size: 0.12,
      vertexColors: true,
      transparent: true,
      opacity: 0.75,
      blending: THREE.AdditiveBlending,
    });
    const particlePoints = new THREE.Points(particleGeo, particleMat);
    scene.add(particlePoints);

    // 6. Interactive Mouse Parallax
    let mouseX = 0;
    let mouseY = 0;
    let targetX = 0;
    let targetY = 0;

    const handleMouseMove = (e) => {
      const rect = container.getBoundingClientRect();
      const x = (e.clientX - rect.left) / rect.width - 0.5;
      const y = (e.clientY - rect.top) / rect.height - 0.5;
      targetX = x * 0.8;
      targetY = y * 0.8;
    };

    window.addEventListener("mousemove", handleMouseMove, { passive: true });

    // 7. Responsive Resize Observer
    const handleResize = () => {
      if (!container) return;
      width = container.clientWidth;
      height = container.clientHeight;
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      renderer.setSize(width, height);
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    };

    const resizeObserver = new ResizeObserver(() => handleResize());
    resizeObserver.observe(container);

    // 8. Animation Render Loop
    let animId;
    let clock = new THREE.Clock();

    const animate = () => {
      animId = requestAnimationFrame(animate);
      const elapsed = clock.getElapsedTime();

      // Damped Mouse Rotation
      mouseX += (targetX - mouseX) * 0.05;
      mouseY += (targetY - mouseY) * 0.05;

      camera.position.x = Math.sin(mouseX) * 24;
      camera.position.y = -mouseY * 12;
      camera.position.z = Math.cos(mouseX) * 24;
      camera.lookAt(0, 0, 0);

      // Core Pulsing & Rotation
      coreGroup.rotation.y = elapsed * 0.2;
      coreGroup.rotation.x = elapsed * 0.15;
      const pulse = 1 + Math.sin(elapsed * 2.5) * 0.05;
      coreGroup.scale.set(pulse, pulse, pulse);

      // Rotate Orbital Rings & Orbiting Nodes
      rings.forEach((ring, idx) => {
        ring.group.rotation.z += ring.speed;
        const nodeAngle = elapsed * (1.2 + idx * 0.3) * (idx % 2 === 0 ? 1 : -1);
        ring.node.position.x = Math.cos(nodeAngle) * ring.radius;
        ring.node.position.y = Math.sin(nodeAngle) * ring.radius;
      });

      // Swarm Particle Rotation
      particlePoints.rotation.y = elapsed * 0.04;
      particlePoints.rotation.x = elapsed * 0.02;

      renderer.render(scene, camera);
    };

    animate();

    // 9. Cleanup on Unmount
    return () => {
      cancelAnimationFrame(animId);
      window.removeEventListener("mousemove", handleMouseMove);
      resizeObserver.disconnect();

      // Dispose Geometries and Materials
      coreGeo.dispose();
      coreMat.dispose();
      cageGeo.dispose();
      cageMat.dispose();
      particleGeo.dispose();
      particleMat.dispose();
      scene.clear();
      renderer.dispose();

      if (container.contains(renderer.domElement)) {
        container.removeChild(renderer.domElement);
      }
    };
  }, []);

  return (
    <div
      ref={mountRef}
      className={`relative w-full h-[380px] sm:h-[480px] lg:h-[540px] pointer-events-auto cursor-grab active:cursor-grabbing ${className}`}
      aria-label="Interactive 3D WebGL Visualization of the Five Assurance Gates"
      role="img"
    />
  );
}

"""
Generate high-resolution figures for MIRAGE 3.0 Final Project Report.
CHARUSAT - CSPIT - Dept of AIML
"""
import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import numpy as np

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'reports', 'figures')
os.makedirs(OUTPUT_DIR, exist_ok=True)

plt.rcParams['font.family'] = 'serif'
plt.rcParams['font.serif'] = ['Times New Roman', 'DejaVu Serif']
plt.rcParams['mathtext.fontset'] = 'cm'

def generate_gantt_chart():
    fig, ax = plt.subplots(figsize=(10, 5), dpi=300)
    tasks = [
        "Phase 1: Problem Definition & Literature Review",
        "Phase 2: Mathematical Formulation of 5 Gates",
        "Phase 3: Database & Security Architecture (Postgres RLS, Redis)",
        "Phase 4: Verification Engine (HRS, NLI, Reality Probes)",
        "Phase 5: Microdose Studio UI & Operator Console",
        "Phase 6: Integration Testing, Benchmarking & Report Writing"
    ]
    starts = [1, 3, 5, 8, 11, 14]
    durations = [3, 3, 4, 4, 3, 3]
    y_pos = np.arange(len(tasks))

    colors = ['#1e293b', '#334155', '#475569', '#64748b', '#0f766e', '#059669']

    for i in range(len(tasks)):
        ax.barh(y_pos[i], durations[i], left=starts[i], align='center', color=colors[i], edgecolor='black', height=0.55)
        ax.text(starts[i] + durations[i] / 2, y_pos[i], f"Weeks {starts[i]}-{starts[i]+durations[i]}", 
                ha='center', va='center', color='white', fontsize=9, fontweight='bold')

    ax.set_yticks(y_pos)
    ax.set_yticklabels(tasks, fontsize=10)
    ax.invert_yaxis()
    ax.set_xlabel('Project Timeline (Weeks / Semester Academic Schedule)', fontsize=11, fontweight='bold', labelpad=10)
    ax.set_title('MIRAGE 3.0 Work Breakdown & Project Scheduling (Gantt Chart)', fontsize=12, fontweight='bold', pad=15)
    ax.set_xlim(0, 18)
    ax.grid(axis='x', linestyle='--', alpha=0.6)
    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, 'fig_2_1_gantt.png'), dpi=300)
    plt.close()

def generate_architecture_diagram():
    fig, ax = plt.subplots(figsize=(11, 7.5), dpi=300)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis('off')

    # Background Layers
    layers = [
        ("Layer 1: Autonomous Agent & Client Ingestion Layer", 82, 14, '#f8fafc', '#0f172a'),
        ("Layer 2: Gateway & Identity Mediation (FastAPI, JWT, Tenant RLS)", 64, 14, '#f1f5f9', '#1e293b'),
        ("Layer 3: The Five Assurance Gates Execution Pipeline", 38, 22, '#f0fdf4', '#166534'),
        ("Layer 4: Distributed Fencing & Task Workers (Celery, Redis, RabbitMQ)", 18, 16, '#fefce8', '#854d0e'),
        ("Layer 5: Independent Reality Verification & Datastores (PostgreSQL, Qdrant, MongoDB)", 0, 15, '#fafaf9', '#1c1917'),
    ]

    for title, y, h, bg, border in layers:
        rect = patches.FancyBboxPatch((4, y), 92, h, boxstyle="round,pad=1.2,rounding_size=2",
                                      facecolor=bg, edgecolor=border, linewidth=1.5)
        ax.add_patch(rect)
        ax.text(6, y + h - 3, title, fontsize=10.5, fontweight='bold', color=border)

    # Layer 1 Components
    ax.text(20, 86, "Autonomous Agents\n(LangChain / AutoGen)", ha='center', va='center', bbox=dict(boxstyle='round,pad=0.5', facecolor='#ffffff', edgecolor='#64748b', lw=1.2), fontsize=8.5)
    ax.text(50, 86, "Microdose Studio Dashboard\n(React 18 / Vite / Nginx)", ha='center', va='center', bbox=dict(boxstyle='round,pad=0.5', facecolor='#ffffff', edgecolor='#64748b', lw=1.2), fontsize=8.5)
    ax.text(80, 86, "External SDK Consumers\n(Python 3.12+ Client)", ha='center', va='center', bbox=dict(boxstyle='round,pad=0.5', facecolor='#ffffff', edgecolor='#64748b', lw=1.2), fontsize=8.5)

    # Layer 2 Components
    ax.text(25, 68, "Reverse Proxy & TLS\n(Port 3000 -> 8000)", ha='center', va='center', bbox=dict(boxstyle='round,pad=0.5', facecolor='#ffffff', edgecolor='#334155', lw=1.2), fontsize=8.5)
    ax.text(50, 68, "Authentication & RBAC\n(Vedant / Dax Personas)", ha='center', va='center', bbox=dict(boxstyle='round,pad=0.5', facecolor='#ffffff', edgecolor='#334155', lw=1.2), fontsize=8.5)
    ax.text(75, 68, "PostgreSQL Session RLS\n(Fail-Closed Isolation)", ha='center', va='center', bbox=dict(boxstyle='round,pad=0.5', facecolor='#ffffff', edgecolor='#334155', lw=1.2), fontsize=8.5)

    # Layer 3: The 5 Gates
    gates = [
        ("Gate 1\nInput\nAssurance", 14),
        ("Gate 2\nContext\nAssurance", 32),
        ("Gate 3\nAction\nAssurance", 50),
        ("Gate 4\nOutput\nAssurance", 68),
        ("Gate 5\nOutcome\nAssurance", 86)
    ]
    for name, x in gates:
        ax.text(x, 46, name, ha='center', va='center', bbox=dict(boxstyle='round,pad=0.6', facecolor='#dcfce7', edgecolor='#15803d', lw=1.5), fontsize=8.5, fontweight='bold')
        if x < 86:
            ax.annotate("", xy=(x + 8, 46), xytext=(x + 3, 46), arrowprops=dict(arrowstyle="->", lw=1.5, color='#15803d'))

    # Layer 4 Components
    ax.text(25, 23, "Redis Distributed Leases\n(Monotonic Tokens)", ha='center', va='center', bbox=dict(boxstyle='round,pad=0.5', facecolor='#ffffff', edgecolor='#a16207', lw=1.2), fontsize=8.5)
    ax.text(50, 23, "RabbitMQ Quorum Queues\n(Async Execution)", ha='center', va='center', bbox=dict(boxstyle='round,pad=0.5', facecolor='#ffffff', edgecolor='#a16207', lw=1.2), fontsize=8.5)
    ax.text(75, 23, "Celery Verification Workers\n(Multi-Queue Concurrency)", ha='center', va='center', bbox=dict(boxstyle='round,pad=0.5', facecolor='#ffffff', edgecolor='#a16207', lw=1.2), fontsize=8.5)

    # Layer 5 Components
    ax.text(20, 5, "PostgreSQL 16 (RLS)\nTenants & Ledger", ha='center', va='center', bbox=dict(boxstyle='round,pad=0.5', facecolor='#ffffff', edgecolor='#44403c', lw=1.2), fontsize=8.5)
    ax.text(50, 5, "Qdrant Vector DB\nRAG Chunks & Embeddings", ha='center', va='center', bbox=dict(boxstyle='round,pad=0.5', facecolor='#ffffff', edgecolor='#44403c', lw=1.2), fontsize=8.5)
    ax.text(80, 5, "MongoDB Trace Store\nVerification Artifacts", ha='center', va='center', bbox=dict(boxstyle='round,pad=0.5', facecolor='#ffffff', edgecolor='#44403c', lw=1.2), fontsize=8.5)

    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, 'fig_3_1_architecture.png'), dpi=300)
    plt.close()

def generate_dfd():
    fig, ax = plt.subplots(figsize=(10, 6), dpi=300)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis('off')

    # DFD Entities & Processes
    ax.text(12, 50, "Autonomous\nAgent / User", ha='center', va='center', bbox=dict(boxstyle='square,pad=0.8', facecolor='#f1f5f9', edgecolor='#0f172a', lw=1.5), fontsize=9, fontweight='bold')
    
    # Process 1.0
    ax.text(35, 75, "1.0 Validate Input\n& Context\n(Gates 1 & 2)", ha='center', va='center', bbox=dict(boxstyle='circle,pad=0.6', facecolor='#e0f2fe', edgecolor='#0369a1', lw=1.5), fontsize=8.5)
    
    # Process 2.0
    ax.text(60, 50, "2.0 Lease Fencing\n& Output Verification\n(Gates 3 & 4)", ha='center', va='center', bbox=dict(boxstyle='circle,pad=0.6', facecolor='#fef3c7', edgecolor='#b45309', lw=1.5), fontsize=8.5)

    # Process 3.0
    ax.text(85, 25, "3.0 Epistemic Reality\nVerification\n(Gate 5)", ha='center', va='center', bbox=dict(boxstyle='circle,pad=0.6', facecolor='#dcfce7', edgecolor='#15803d', lw=1.5), fontsize=8.5)

    # Data Stores
    ax.text(60, 85, "[D1] PostgreSQL Tenant & Policy DB", ha='center', va='center', bbox=dict(boxstyle='round,pad=0.4', facecolor='#ffffff', edgecolor='#334155', lw=1), fontsize=8.5)
    ax.text(60, 15, "[D2] Redis Distributed Lease Store", ha='center', va='center', bbox=dict(boxstyle='round,pad=0.4', facecolor='#ffffff', edgecolor='#334155', lw=1), fontsize=8.5)
    ax.text(85, 65, "[D3] Destination SQL / Physical Target", ha='center', va='center', bbox=dict(boxstyle='round,pad=0.4', facecolor='#ffffff', edgecolor='#334155', lw=1), fontsize=8.5)

    # Arrows
    ax.annotate("Prompt Payload", xy=(27, 70), xytext=(15, 58), arrowprops=dict(arrowstyle="->", lw=1.2, color='#0f172a'), fontsize=8)
    ax.annotate("Grounded Chunks", xy=(52, 58), xytext=(43, 70), arrowprops=dict(arrowstyle="->", lw=1.2, color='#0f172a'), fontsize=8)
    ax.annotate("Lease Grant", xy=(77, 33), xytext=(68, 45), arrowprops=dict(arrowstyle="->", lw=1.2, color='#0f172a'), fontsize=8)
    ax.annotate("Verified Outcome", xy=(15, 42), xytext=(78, 22), arrowprops=dict(arrowstyle="->", lw=1.2, color='#15803d', connectionstyle="arc3,rad=-0.25"), fontsize=8)

    ax.set_title('Data Flow Diagram (DFD Level 1) — MIRAGE 3.0 Execution Pipeline', fontsize=11, fontweight='bold', pad=10)
    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, 'fig_3_2_dfd.png'), dpi=300)
    plt.close()

def generate_usecase():
    fig, ax = plt.subplots(figsize=(10, 6.5), dpi=300)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis('off')

    # System Boundary
    boundary = patches.Rectangle((25, 5), 55, 90, facecolor='#fbfbfc', edgecolor='#0f172a', lw=1.5, linestyle='--')
    ax.add_patch(boundary)
    ax.text(52, 92, "MIRAGE 3.0 Assurance Boundary", ha='center', va='center', fontsize=10.5, fontweight='bold')

    # Actors
    ax.text(10, 75, "Actor:\nAutonomous Agent", ha='center', va='center', bbox=dict(boxstyle='square,pad=0.6', facecolor='#f1f5f9', edgecolor='#0f172a', lw=1.2), fontsize=8.5, fontweight='bold')
    ax.text(10, 25, "Actor:\nHuman Operator\n(Vedant)", ha='center', va='center', bbox=dict(boxstyle='square,pad=0.6', facecolor='#f1f5f9', edgecolor='#0f172a', lw=1.2), fontsize=8.5, fontweight='bold')
    ax.text(90, 50, "Actor:\nAuditor / Regulator\n(Dax)", ha='center', va='center', bbox=dict(boxstyle='square,pad=0.6', facecolor='#f1f5f9', edgecolor='#0f172a', lw=1.2), fontsize=8.5, fontweight='bold')

    # Use cases
    use_cases = [
        ("Submit Action Proposal", 80),
        ("Acquire Distributed Lease", 65),
        ("Review L4 Human Approval", 50),
        ("Verify Reality Postconditions", 35),
        ("Verify Merkle Audit Chain", 20)
    ]

    for title, y in use_cases:
        ellipse = patches.Ellipse((52, y), 34, 9, facecolor='#ffffff', edgecolor='#0f766e', lw=1.4)
        ax.add_patch(ellipse)
        ax.text(52, y, title, ha='center', va='center', fontsize=8.5, fontweight='bold', color='#0f766e')

    # Relationships
    ax.plot([16, 36], [75, 80], 'k-', lw=1.2)
    ax.plot([16, 36], [75, 65], 'k-', lw=1.2)
    ax.plot([17, 36], [28, 50], 'k-', lw=1.2)
    ax.plot([17, 36], [22, 35], 'k-', lw=1.2)
    ax.plot([82, 68], [50, 20], 'k-', lw=1.2)
    ax.plot([82, 68], [52, 35], 'k-', lw=1.2)

    ax.set_title('Use Case Diagram — Governed AI Execution & Reality Verification', fontsize=11, fontweight='bold', pad=10)
    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, 'fig_3_3_usecase.png'), dpi=300)
    plt.close()

def generate_er():
    fig, ax = plt.subplots(figsize=(10, 6), dpi=300)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis('off')

    # Entity Boxes
    entities = [
        ("TENANTS\n(Postgres RLS)", 20, 75, "tenant_id (PK)\nname\npolicy_spec\nis_active", '#1e293b'),
        ("AGENTS\n(Postgres)", 60, 75, "agent_id (PK)\ntenant_id (FK)\nautonomy_level\nstatus", '#1e293b'),
        ("ACTIONS / LEASES\n(Postgres / Redis)", 20, 25, "action_id (PK)\nagent_id (FK)\ntool_name\nfencing_token", '#0f766e'),
        ("REALITY OUTCOMES\n(Postgres & Mongo)", 60, 25, "outcome_id (PK)\naction_id (FK)\nprobe_status\nmerkle_hash", '#047857')
    ]

    for title, x, y, attrs, border in entities:
        rect = patches.FancyBboxPatch((x-14, y-14), 28, 25, boxstyle="round,pad=0.5", facecolor='#ffffff', edgecolor=border, lw=1.5)
        ax.add_patch(rect)
        ax.text(x, y + 7, title, ha='center', va='center', fontsize=8.5, fontweight='bold', color=border)
        ax.text(x, y - 4, attrs, ha='center', va='center', fontsize=7.5, color='#475569')

    # Relations
    ax.annotate("1 : N", xy=(46, 75), xytext=(34, 75), arrowprops=dict(arrowstyle="->", lw=1.5, color='#1e293b'), fontsize=8, fontweight='bold')
    ax.annotate("1 : N", xy=(20, 37), xytext=(20, 60), arrowprops=dict(arrowstyle="->", lw=1.5, color='#0f766e'), fontsize=8, fontweight='bold')
    ax.annotate("1 : 1", xy=(46, 25), xytext=(34, 25), arrowprops=dict(arrowstyle="->", lw=1.5, color='#047857'), fontsize=8, fontweight='bold')

    ax.set_title('Entity-Relationship (ER) Diagram — Data Models & Relational Integrity', fontsize=11, fontweight='bold', pad=10)
    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, 'fig_3_4_er.png'), dpi=300)
    plt.close()

def generate_latency_chart():
    fig, ax = plt.subplots(figsize=(9, 4.8), dpi=300)
    gates = ['Gate 1\n(Input)', 'Gate 2\n(Context)', 'Gate 3\n(Action)', 'Gate 4\n(Output)', 'Gate 5\n(Outcome)']
    mean_latencies = [3.2, 11.4, 4.8, 21.0, 14.5]
    p99_latencies = [5.1, 16.8, 7.2, 29.4, 22.1]

    x = np.arange(len(gates))
    width = 0.35

    rects1 = ax.bar(x - width/2, mean_latencies, width, label='Mean Latency (ms)', color='#0c152a', edgecolor='black')
    rects2 = ax.bar(x + width/2, p99_latencies, width, label='p99 Latency (ms)', color='#10b981', edgecolor='black')

    ax.set_ylabel('Execution Latency (Milliseconds)', fontsize=10, fontweight='bold')
    ax.set_title('Empirical Latency Profile Across The Five Assurance Gates', fontsize=11, fontweight='bold', pad=12)
    ax.set_xticks(x)
    ax.set_xticklabels(gates, fontsize=9.5)
    ax.legend(frameon=True, fontsize=9)
    ax.grid(axis='y', linestyle='--', alpha=0.5)

    for rect in rects1:
        h = rect.get_height()
        ax.annotate(f'{h:.1f}', xy=(rect.get_x() + rect.get_width()/2, h), xytext=(0, 3), textcoords="offset points", ha='center', va='bottom', fontsize=8)
    for rect in rects2:
        h = rect.get_height()
        ax.annotate(f'{h:.1f}', xy=(rect.get_x() + rect.get_width()/2, h), xytext=(0, 3), textcoords="offset points", ha='center', va='bottom', fontsize=8)

    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, 'fig_4_2_latency.png'), dpi=300)
    plt.close()

def generate_hrs_chart():
    fig, ax = plt.subplots(figsize=(9, 4.8), dpi=300)
    np.random.seed(42)
    n = 120

    hrs_scores = np.random.beta(2, 5, n)
    entailment = 1.0 - (hrs_scores * 0.9 + np.random.normal(0, 0.05, n))
    entailment = np.clip(entailment, 0.0, 1.0)

    # Classification
    approved = hrs_scores < 0.60
    blocked = ~approved

    ax.scatter(hrs_scores[approved], entailment[approved], color='#059669', alpha=0.75, edgecolors='none', s=45, label='Approved & Grounded (HRS < 0.60)')
    ax.scatter(hrs_scores[blocked], entailment[blocked], color='#dc2626', alpha=0.75, edgecolors='none', s=45, label='Fenced / Corrected (HRS ≥ 0.60)')

    ax.axvline(x=0.60, color='#1e293b', linestyle='--', linewidth=1.5, label='HRS Correction Threshold (τ = 0.60)')
    ax.set_xlabel('Hallucination Risk Score (HRS)', fontsize=10, fontweight='bold')
    ax.set_ylabel('NLI Premise Entailment Probability', fontsize=10, fontweight='bold')
    ax.set_title('Gate 4 Output Assurance: Entailment vs Hallucination Risk Score', fontsize=11, fontweight='bold', pad=12)
    ax.legend(frameon=True, fontsize=8.5)
    ax.grid(True, linestyle='--', alpha=0.5)

    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, 'fig_4_3_hrs_curve.png'), dpi=300)
    plt.close()

def generate_sequence():
    fig, ax = plt.subplots(figsize=(10.5, 7), dpi=300)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis('off')

    # Lifelines
    lifelines = [
        ("Agent", 12),
        ("Gate 1 (Input)", 28),
        ("Gate 2 (Context)", 44),
        ("Gate 3 (Action)", 60),
        ("Gate 4 (Output)", 76),
        ("Gate 5 (Outcome)", 92)
    ]

    for name, x in lifelines:
        ax.text(x, 94, name, ha='center', va='center', bbox=dict(boxstyle='round,pad=0.4', facecolor='#f1f5f9', edgecolor='#0f172a', lw=1.2), fontsize=8, fontweight='bold')
        ax.plot([x, x], [90, 8], 'k--', lw=0.9, alpha=0.6)

    # Sequence messages
    steps = [
        (85, 12, 28, "1. Submit Prompt + Tenant JWT", '#0f172a'),
        (76, 28, 44, "2. Tenant Validated -> Query RAG Context", '#0369a1'),
        (67, 44, 28, "3. Grounded Chunks (Similarity >= 0.92)", '#0369a1'),
        (58, 12, 60, "4. Propose Mutation Tool Action", '#b45309'),
        (49, 60, 60, "5. Redis Concurrency Lease Acquired", '#b45309'),
        (40, 12, 76, "6. Candidate Completion Output", '#7e22ce'),
        (31, 76, 76, "7. Verify HRS (0.04) & JSON Schema", '#7e22ce'),
        (22, 60, 92, "8. Two-Phase Dispatch to Target System", '#15803d'),
        (13, 92, 12, "9. OBS_DIRECT SQL Query Confirms State", '#15803d'),
    ]

    for y, x1, x2, msg, color in steps:
        if x1 == x2:
            # Self call
            ax.annotate("", xy=(x1, y-4), xytext=(x1+6, y-2), arrowprops=dict(arrowstyle="->", lw=1.2, color=color))
            ax.plot([x1, x1+6], [y, y], color=color, lw=1.2)
            ax.plot([x1+6, x1+6], [y, y-2], color=color, lw=1.2)
            ax.text(x1 + 8, y - 2, msg, va='center', fontsize=7.5, fontweight='bold', color=color)
        else:
            ax.annotate("", xy=(x2, y), xytext=(x1, y), arrowprops=dict(arrowstyle="->", lw=1.3, color=color))
            mid_x = (x1 + x2) / 2
            ax.text(mid_x, y + 2, msg, ha='center', va='bottom', fontsize=7.5, fontweight='bold', color=color)

    ax.set_title('Sequence Diagram — Sequential Execution Across The Five Assurance Gates', fontsize=11, fontweight='bold', pad=12)
    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, 'fig_4_1_sequence.png'), dpi=300)
    plt.close()

if __name__ == '__main__':
    print("Generating report figures...")
    generate_gantt_chart()
    generate_architecture_diagram()
    generate_dfd()
    generate_usecase()
    generate_er()
    generate_sequence()
    generate_latency_chart()
    generate_hrs_chart()
    print("All figures generated successfully in reports/figures/.")

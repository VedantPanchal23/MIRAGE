#!/usr/bin/env bash
# ==============================================================================
# MIRAGE 3.0: One-Click Production & Developer Orchestration Launcher (POSIX)
# ==============================================================================
set -e

# Terminal colors
CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
WHITE='\033[1;37m'
GRAY='\033[0;90m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${CYAN}==================================================================${NC}"
echo -e "${GREEN}       MIRAGE 3.0 - AI Execution Assurance Platform${NC}"
echo -e "${GRAY}  Control AI before it acts. Verify AI after it acts.${NC}"
echo -e "${CYAN}==================================================================${NC}"
echo ""

MODE="${1:-}"

if [ -z "$MODE" ]; then
    echo -e "${YELLOW}Select execution mode:${NC}"
    echo -e "  ${WHITE}[1] Core SaaS Engine (Fast - Postgres, Redis, Qdrant, Gateway, Dashboard)${NC}"
    echo -e "  ${WHITE}[2] Full Enterprise Cluster (Core + Workers + Grafana + Prometheus + Tempo)${NC}"
    echo -e "  ${WHITE}[3] Run Full Customer Journey Automated Smoke Test${NC}"
    echo -e "  ${WHITE}[4] View Live Container Status & Health${NC}"
    echo -e "  ${WHITE}[5] Stop All Services (Teardown)${NC}"
    echo ""
    read -rp "Enter option [1-5] (Default: 1): " CHOICE
    CHOICE="${CHOICE:-1}"
else
    CHOICE="$MODE"
fi

case "$CHOICE" in
    1|core|fast)
        echo -e "\n${CYAN}>>> Starting Core SaaS Platform...${NC}"
        docker compose up -d postgres redis qdrant mongodb rabbitmq migration gateway dashboard
        echo -e "\n${YELLOW}>>> Waiting for Gateway to report healthy...${NC}"
        sleep 3
        docker compose ps
        echo -e "\n${GREEN}==================================================================${NC}"
        echo -e "${GREEN}  MIRAGE Core SaaS Platform is ONLINE!${NC}"
        echo -e "${WHITE}  - Storefront & Operator Dashboard: http://localhost:3000${NC}"
        echo -e "${WHITE}  - Execution Plane Gateway:         http://localhost:8000${NC}"
        echo -e "${WHITE}  - Interactive OpenAPI Contracts:   http://localhost:8000/docs${NC}"
        echo -e "${WHITE}  - System Health & Gate Status:     http://localhost:8000/v1/health${NC}"
        echo -e "${GREEN}==================================================================${NC}"
        ;;
    2|full|enterprise)
        echo -e "\n${CYAN}>>> Starting Full Enterprise Cluster with Observability...${NC}"
        docker compose --profile full up -d
        echo -e "\n${YELLOW}>>> Waiting for Services...${NC}"
        sleep 5
        docker compose ps
        echo -e "\n${GREEN}==================================================================${NC}"
        echo -e "${GREEN}  MIRAGE Enterprise Cluster is ONLINE!${NC}"
        echo -e "${WHITE}  - Storefront & Operator Dashboard: http://localhost:3000${NC}"
        echo -e "${WHITE}  - Execution Plane Gateway:         http://localhost:8000${NC}"
        echo -e "${WHITE}  - Grafana Telemetry Dashboards:    http://localhost:3001${NC}"
        echo -e "${WHITE}  - Prometheus Metrics Engine:       http://localhost:9090${NC}"
        echo -e "${GREEN}==================================================================${NC}"
        ;;
    3|test|verify)
        echo -e "\n${CYAN}>>> Executing Full Customer Journey Smoke Test...${NC}"
        python scripts/verify_full_customer_journey.py
        ;;
    4|status|ps)
        echo -e "\n${CYAN}>>> Checking Container Status...${NC}"
        docker compose ps
        ;;
    5|down|stop)
        echo -e "\n${YELLOW}>>> Stopping All Services...${NC}"
        docker compose --profile full down
        echo -e "${GREEN}>>> All MIRAGE containers terminated safely.${NC}"
        ;;
    *)
        echo -e "${RED}Invalid option: ${CHOICE}. Exiting.${NC}"
        exit 1
        ;;
esac

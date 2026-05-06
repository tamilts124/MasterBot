# 🤖 WhatsApp AI Agent Automation (Hardened)

![GitHub Workflow Status](https://img.shields.io/github/actions/workflow/status/tamilts124/AI_CLI/developer_agent.yml?style=for-the-badge)
![Python Version](https://img.shields.io/badge/Python-3.10+-blue?style=for-the-badge&logo=python)
![Docker](https://img.shields.io/badge/Docker-Enabled-2496ED?style=for-the-badge&logo=docker)
![Tor](https://img.shields.io/badge/Tor-Integrated-7D4698?style=for-the-badge&logo=torproject)

A premium, hardened autonomous developer agent system. This project leverages **Docker**, **GitHub Actions**, **Tor Network**, and **Ollama** to provide a resilient, 24/7 automated development experience with multi-key support and IP rotation.

## 🌟 Key Features

-   **Tor IP Rotation**: All API requests are routed through the **Tor Network** (SOCKS5 proxy). The agent automatically requests a new Tor circuit (`NEWNYM`) on retries and rotations to bypass connection drops and IP rate limits.
-   **Hardened Execution Loop**: 
    -   **Selective Retries**: Intelligent retry logic for transient "Server disconnected" errors.
    -   **Multi-Key Cycling**: Automatically rotates through a list of Ollama API keys when limits are reached.
    -   **Global Wait Cycle**: If all keys are exhausted, the agent enters a 15-minute "cool-down" before restarting the cycle, ensuring continuous progress.
-   **Automated Deployment**: GitHub Actions triggers on schedule or manual dispatch.
-   **Emergency Progress Save**: Automatically stages, commits, and pushes changes to GitHub whenever a session is interrupted or a key is rotated.
-   **Dockerized API**: Runs the [WhatsApp API](https://github.com/tamilts124/WhatsApp_API) in a stable container for communication.

## 🛠 Architecture

1.  **Workflow Trigger**: Scheduled via CRON or manual dispatch.
2.  **Network Shield**: **Tor Service** initializes with Control Port access for IP rotation.
3.  **Environment Setup**: Ubuntu-latest runner with Docker, Python 3.10, and Tor.
4.  **Authentication**: Securely restores `auth_info` WhatsApp session data.
5.  **Service Startup**: WhatsApp API container initializes on port 3000.
6.  **Hardened Agent**: Python developer agent executes with the **Master Architect Prompt**, cycling keys and IPs as needed.

## 🔐 Required Secrets & Variables

| Name | Type | Description |
| :--- | :--- | :--- |
| `OLLAMA_API_KEYS` | Secret | Comma-separated list of Ollama API keys for rotation. |
| `TARGET_REPO_TOKEN` | Secret | GitHub PAT for pushing changes to the target repository. |
| `AUTH_INFO_PASSWORD` | Secret | Password for the `auth_info.7z` encrypted file. |
| `WHATSAPP_NUMBER1` | Secret | Primary WhatsApp number for SOS communication. |
| `DEVELOPER_PROMPT` | Variable | The "Master Architect" instructions for the developer agent. |
| `TARGET_REPO_URL` | Variable | The URL of the repository the agent is developing. |
| `DEVELOPER_MODEL` | Variable | The Ollama model to use (e.g., `qwen3-coder:480b-cloud`). |

## 🚀 Getting Started

1.  Clone the repository.
2.  Ensure `auth_info.7z` is present in the root directory for WhatsApp connectivity.
3.  Configure the Secrets and Variables in your GitHub repository settings.
4.  Trigger the **AI Developer Agent** workflow from the **Actions** tab.

---

Built with ❤️ by [Tamil](https://github.com/tamilts124)

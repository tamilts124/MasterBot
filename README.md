# 🤖 WhatsApp AI Agent Automation

![GitHub Workflow Status](https://img.shields.io/github/actions/workflow/status/tamilts124/AI_CLI/whatsapp_agent.yml?style=for-the-badge)
![Python Version](https://img.shields.io/badge/Python-3.10+-blue?style=for-the-badge&logo=python)
![Docker](https://img.shields.io/badge/Docker-Enabled-2496ED?style=for-the-badge&logo=docker)

A premium, automated solution for running a ReAct AI agent on WhatsApp. This project leverages **Docker**, **GitHub Actions**, and **Ollama** to provide a seamless, scheduled AI interaction experience.

## 🌟 Key Features

-   **Automated Deployment**: GitHub Actions triggers daily at 5:00 AM IST (23:30 UTC) and 10:00 PM UTC.
-   **Encrypted Session Recovery**: Securely unzips WhatsApp session data using 7z with AES-256 encryption.
-   **Dockerized API**: Runs the [WhatsApp API](https://github.com/tamilts124/WhatsApp_API) in a lightweight container for maximum stability.
-   **Advanced AI Agent**: Powered by `gemma4:31b-cloud` via Ollama for intelligent tool usage and reasoning.

## 🛠 Architecture

1.  **Workflow Trigger**: Scheduled via CRON or manual trigger.
2.  **Environment Setup**: Ubuntu-latest runner with Docker and Python 3.10.
3.  **Authentication**: Securely restores `auth_info` session data.
4.  **Service Startup**: WhatsApp API container initializes on port 3000.
5.  **Agent Execution**: Python agent processes the prompt and communicates with WhatsApp/Ollama.

## 🔐 Required Secrets

To run this workflow, configure the following secrets in your GitHub repository:

| Secret | Description |
| :--- | :--- |
| `AUTH_INFO_PASSWORD` | Password for the `auth_info.7z` encrypted file. |
| `OLLAMA_API_URL` | Base URL for Ollama API (e.g., `https://ollama.com`). |
| `OLLAMA_API_KEY` | API Key for your Ollama endpoint. |
| `AGENT_PROMPT` | The primary instruction or query for the agent. |
| `WHATSAPP_NUMBER` | The target WhatsApp ID/Number (e.g., `1234567890@c.us`). |

## 🚀 Getting Started

1.  Clone the repository.
2.  Ensure `auth_info.7z` is present in the root directory.
3.  Add the required secrets to your GitHub repository settings.
4.  The workflow will run automatically on schedule, or you can trigger it manually from the **Actions** tab.

---

Built with ❤️ by [Tamil](https://github.com/tamilts124)

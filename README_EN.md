# LandPPT - AI-Powered PPT Generation Platform

[![GitHub stars](https://img.shields.io/github/stars/sligter/LandPPT?style=flat-square)](https://github.com/sligter/LandPPT/stargazers)
[![GitHub forks](https://img.shields.io/github/forks/sligter/LandPPT?style=flat-square)](https://github.com/sligter/LandPPT/network)
[![GitHub issues](https://img.shields.io/github/issues/sligter/LandPPT?style=flat-square)](https://github.com/sligter/LandPPT/issues)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg?style=flat-square)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg?style=flat-square)](https://www.python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-green.svg?style=flat-square)](https://fastapi.tiangolo.com)
[![Docker](https://img.shields.io/badge/docker-supported-blue.svg?style=flat-square)](https://hub.docker.com/r/bradleylzh/landppt)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/sligter/LandPPT)

---

## 🎯 Open to Opportunities

I'm currently seeking **Agent Development** related job opportunities. If you're interested in my projects or have suitable positions/collaboration opportunities, feel free to reach out!

[![Email](https://img.shields.io/badge/📧_Email-ai%40yydsapp.com-blue?style=for-the-badge)](mailto:ai@yydsapp.com)

---


**English** | [中文](README.md)

---

## 📋 Table of Contents

- [Project Overview](#-project-overview)
- [Feature Highlights](#-feature-highlights)
- [Key Features](#-key-features)
- [Quick Start](#-quick-start)
- [Usage Guide](#-usage-guide)
- [Configuration](#-configuration)
- [API Documentation](#-api-documentation)
- [Tech Stack](#️-tech-stack)
- [Contributing](#-contributing)
- [FAQ](#-faq)
- [License](#-license)

## 🎯 Project Overview

LandPPT is an intelligent presentation generation platform powered by Large Language Models (LLMs) that automatically converts document content into professional PPT presentations. The platform integrates multiple AI models, intelligent image processing, deep research capabilities, and rich template systems, enabling users to effortlessly create high-quality presentations.


![image](https://img.pub/p/4b07dee6cf3cef023bd8.png)

![image](https://img.pub/p/1f9e79326ddeae3b8716.png)

![image](https://img.pub/p/02bac27fe8097c012d9e.png)

![image](https://img.pub/p/9a38b57c6f5f470ad59b.png)

![image](https://img.pub/p/47090624aec2d337f0df.png)

![image](https://img.pub/p/bebe9fe671d0125ceac6.png)

![image](https://img.pub/p/b1655542c516845fd924.png)

![image](https://img.pub/p/0d2ffc650792c4a133a4.png)

## 🌟 Feature Highlights

- **🚀 One-Click Generation**: From topic to complete PPT, fully automated AI processing
- **🎨 Smart Image Matching**: AI automatically matches the most suitable images with multi-source support and reference image generation
- **🔍 Deep Research**: Integrated multiple search engines for latest and comprehensive information
- **🎤 Speech Script Generation**: Intelligent generation of accompanying speech scripts with multiple export formats
- **👁️ Visual Reference**: AI editing assistant supports image upload and visual content analysis
- **📂 Multiple File Upload**: Support uploading multiple files simultaneously for efficient batch processing
- **⚡ Batch Generation**: Support batch PPT page generation for significantly improved speed
- **🎯 Custom Model Selection**: Customize model selection by function module for precise cost control
- **📝 Notes Export**: Support exporting speech scripts to PPT notes
- **🖼️ Image Export**: Support exporting PPT in image format
- **📱 Responsive Design**: Perfect adaptation to various devices and screen sizes
- **🔒 Enterprise Security**: Support for local deployment with controllable data security

## ✨ Key Features

### 🤖 Multi-AI Provider Support
- **OpenAI GPT Series**: GPT-4o, GPT-4o-mini and other latest models
- **Anthropic Claude**: Claude-3.5 Sonnet, Claude-3 Haiku series models
- **Google Gemini**: Gemini-1.5 Flash, Gemini-1.5 Pro series models with custom endpoint support
- **Azure OpenAI**: Enterprise-grade AI services with custom deployments
- **Ollama**: Locally deployed open-source models supporting Llama, Mistral, etc.

### 📄 Powerful File Processing
- **Multi-format Support**: PDF, Word, Markdown, TXT, Excel and more formats
- **Intelligent Parsing**: High-quality content extraction using MinerU and MarkItDown
- **Deep Research**: Multi-source research with Tavily API and SearXNG integration
- **Content Enhancement**: Automatic web content extraction and intelligent summarization

### 🎨 Intelligent Image Processing System
- **Multi-source Image Acquisition**: Local gallery, network search, and AI generation in one
- **Network Image Search**: Support for premium galleries like Pixabay, Unsplash
- **AI Image Generation**: Integration with DALL-E, SiliconFlow, Pollinations services
- **Smart Image Selection**: AI automatically matches the most suitable image content
- **Image Processing Optimization**: Automatic resizing, format conversion, quality optimization

### 🔍 Enhanced Research Capabilities
- **Multi-engine Search**: Dual engine support with Tavily and SearXNG
- **Deep Content Extraction**: Intelligent web content parsing and structured processing
- **Multi-language Support**: Support for Chinese, English and other languages
- **Real-time Information**: Access to latest web information and data

### 🎨 Rich Template System
- **Global Master Templates**: Unified HTML template system with responsive design
- **Diverse Layouts**: AI-generated creative page layouts and design styles
- **Scenario-based Templates**: Professional templates for general, tourism, education scenarios
- **Custom Templates**: Support for importing and creating personalized templates
- **Reference Image Generation**: AI template generation supports reference images for intelligent design style matching

### 📊 Complete Project Management
- **Three-stage Workflow**: Requirements confirmation → Outline generation → PPT generation
- **Visual Editing**: Intuitive outline editor with real-time preview
- **Version Management**: Project history and version rollback functionality
- **Batch Operations**: Support for batch generation and processing multiple projects

### 🌐 Modern Web Interface
- **Intuitive Operation**: User-friendly responsive web interface
- **AI Chat Editing**: Sidebar AI editing with real-time conversation support and visual references
- **Speech Script Generation**: Support for single/multiple/all slide speech script generation, export to DOCX/Markdown formats
- **Multi-format Export**: PDF/HTML/PPTX export support
- **Real-time Preview**: 16:9 standard ratio real-time page preview

## 🚀 Quick Start

### System Requirements
- Python 3.11+
- SQLite 3
- Docker (optional)

### Local Installation

#### Method 1: uv Setup (Recommended)

```bash
# Clone the repository
git clone https://github.com/sligter/LandPPT.git
cd LandPPT

# Install uv (if not already installed)
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Sync environment with uv
uv sync

# Install additional dependencies (optional, for PPTX export)
uv pip install apryse-sdk --extra-index-url=https://pypi.apryse.com

# Configure environment variables
cp .env.example .env
# Edit .env file and configure your AI API keys

# Start the service
uv run python run.py
```

#### Method 2: Traditional pip Installation

```bash
# Clone the repository
git clone https://github.com/sligter/LandPPT.git
cd LandPPT

# Create virtual environment
python -m venv venv
# Activate virtual environment
# Windows
venv\Scripts\activate
# macOS/Linux
source venv/bin/activate

# Install dependencies
pip install -e .

# Configure environment variables
cp .env.example .env
# Edit .env file and configure your AI API keys

# Start the service
python run.py
```

### Docker Deployment

#### Using Pre-built Image (Recommended)

```bash
# Pull the latest image
docker pull bradleylzh/landppt:latest

# Run container
docker run -d \
  --name landppt \
  -p 8000:8000 \
  -v $(pwd)/.env:/app/.env \
  -v landppt_data:/app/data \
  -v landppt_reports:/app/research_reports \
  -v landppt_cache:/app/temp \
  bradleylzh/landppt:latest

# View logs
docker logs -f landppt
```

> **Note**: Make sure to create and configure the `.env` file with necessary API keys before running.



## 📖 Usage Guide

### 1. Access Web Interface
After starting the service, visit:
- **Web Interface**: http://localhost:8000
- **API Documentation**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/health

[Initial account:
`admin`
password:
`admin123`]

### 2. Configure AI Providers
Configure your AI API keys in the settings page:
- OpenAI API Key
- Anthropic API Key
- Google API Key
- 302.AI API Key
- Or configure local Ollama service

### 3. Create PPT Projects
1. **Requirements Confirmation**: Input topic, select audience, set page range, choose scenario template
2. **Outline Generation**: AI intelligently generates structured outline with visual editing support
3. **Content Research**: Optionally enable deep research functionality to get latest relevant information
4. **Image Configuration**: Configure image acquisition methods (local/network/AI generation)
5. **PPT Generation**: Generate complete HTML presentation based on outline

### 4. Edit and Export
- Use AI chat functionality for real-time content and style editing with image upload for visual references
- Support image replacement and optimization, AI template generation can reference uploaded images
- Generate accompanying speech scripts with single/multiple/all slide modes
- Export as PDF, HTML, PPTX, and speech script DOCX/Markdown formats
- Save project versions and history
- Support batch processing and template reuse

## 🔧 Configuration

### Environment Variables

Main configuration items (see `.env.example` for details):

```bash
# AI Provider Configuration
DEFAULT_AI_PROVIDER=openai
OPENAI_API_KEY=your_openai_api_key_here
ANTHROPIC_API_KEY=your_anthropic_api_key_here
GOOGLE_API_KEY=your_google_api_key_here
GOOGLE_BASE_URL=https://generativelanguage.googleapis.com  # Custom Gemini endpoint

# Server Configuration
HOST=0.0.0.0
PORT=8000
SECRET_KEY=your-secure-secret-key

# Research Functionality Configuration
TAVILY_API_KEY=your_tavily_api_key_here        # Tavily search engine
SEARXNG_HOST=http://localhost:8888             # SearXNG instance URL
RESEARCH_PROVIDER=tavily                       # Research provider: tavily, searxng, both

# Image Service Configuration
ENABLE_IMAGE_SERVICE=true                      # Enable image service
PIXABAY_API_KEY=your_pixabay_api_key_here     # Pixabay gallery
UNSPLASH_ACCESS_KEY=your_unsplash_key_here    # Unsplash gallery
SILICONFLOW_API_KEY=your_siliconflow_key_here # AI image generation
POLLINATIONS_API_TOKEN=your_pollinations_token # Pollinations AI

# Export Functionality Configuration
APRYSE_LICENSE_KEY=your_apryse_key_here       # PPTX export

# Generation Parameters
MAX_TOKENS=8192
TEMPERATURE=0.7
```

## 📚 API Documentation

After starting the service, visit:
- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`

## 🛠️ Tech Stack

### Backend Technologies
- **FastAPI**: Modern Python web framework with async support
- **SQLAlchemy**: ORM database operations supporting multiple databases
- **Pydantic**: Data validation and serialization with type safety
- **Uvicorn**: High-performance ASGI server

### AI Integration
- **OpenAI**: GPT-4o, GPT-4o-mini and other latest models
- **Anthropic**: Claude-4.5 series models
- **Google AI**: Gemini-2.5 series models
- **LangChain**: AI application development framework and toolchain
- **Ollama**: Local model deployment and management

### File Processing
- **MinerU**: High-quality PDF intelligent parsing and structured extraction
- **MarkItDown**: Multi-format document conversion (Word, Excel, PowerPoint, etc.)
- **BeautifulSoup4**: HTML/XML parsing and processing

### Image Processing
- **Pillow**: Image processing and format conversion
- **OpenAI DALL-E**: AI image generation
- **SiliconFlow**: Domestic AI image generation service
- **Pollinations**: Open-source AI image generation platform

### Research Capabilities
- **Tavily**: Professional search engine API
- **SearXNG**: Open-source meta search engine
- **HTTPX**: Asynchronous HTTP client
- **Playwright**: Web content extraction

### Export Functionality
- **Playwright**: High-quality HTML to PDF export
- **Apryse SDK**: Professional PPTX generation and conversion

## 🤝 Contributing

We welcome all forms of contributions!

### How to Contribute
1. Fork the repository
2. Create a feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

For details, please see [Contributing Guide](CONTRIBUTING.md).

### Reporting Issues
If you find bugs or have feature suggestions, please create a new issue on the [Issues](https://github.com/sligter/LandPPT/issues) page.

## ❓ FAQ

### Q: Which AI models are supported?
A: Supports OpenAI GPT, Anthropic Claude, Google Gemini, Azure OpenAI, and Ollama local models. You can switch between different AI providers in the configuration page.

### Q: How to configure image functionality?
A: Configure the corresponding API keys in the `.env` file:
- Pixabay: `PIXABAY_API_KEY`
- Unsplash: `UNSPLASH_ACCESS_KEY`
- AI Generation: `SILICONFLOW_API_KEY` or `POLLINATIONS_API_TOKEN`

### Q: When using a reverse proxy (such as Nginx, Apache, etc.), if `base_url` is not configured correctly, the following issues may occur:
- Image links still display as `localhost:8000`
- Images cannot be loaded correctly on the front end
- Image preview and download functions do not function properly

A: Configure via the web interface

1. Visit the system configuration page: `https://your-domain.com/ai-config`
2. Switch to the "Application Configuration" tab
3. Enter your proxy domain name in the "Base URL (BASE_URL)" field
4. For example: `https://your-domain.com` or `http://your-domain.com:8080`
5. Click "Save Application Configuration"

### Q: How to use the research functionality?
A: Configure `TAVILY_API_KEY` or deploy a SearXNG instance, then enable research functionality when creating PPTs to automatically get relevant information.

### Q: Does it support local deployment?
A: Fully supports local deployment, can use Docker or direct installation. Supports Ollama local models without relying on external APIs.

### Q: How to export PPTX format?
A: Need to configure `APRYSE_LICENSE_KEY`, then select PPTX format in export options.

## 📄 License

This project is licensed under the Apache License 2.0. See the [LICENSE](LICENSE) file for details.

## 🌟 Star History

[![Star History Chart](https://api.star-history.com/svg?repos=sligter/LandPPT&type=Date)](https://star-history.com/#sligter/LandPPT&Date)

## 📞 Contact Us

- **Project Homepage**: https://github.com/sligter/LandPPT
- **Issue Reporting**: https://github.com/sligter/LandPPT/issues
- **Discussions**: https://github.com/sligter/LandPPT/discussions
- **Community**: https://t.me/+EaOfoceoNwdhNDVl

![LandPPT](https://github.com/sligter/LandPPT/assets/e3aeeb9f-9d52-46a5-8768-387c7fa3a427)
---

<div align="center">

**If this project helps you, please give us a ⭐️ Star!**

Made with ❤️ by the LandPPT Team

</div>

# Docs2Skill

**Automatically convert any documentation website into a Claude Code Skill.**

Docs2Skill scrapes documentation websites, converts them to Markdown, and uses an LLM to generate a complete Claude Code Skill that enables Claude to effectively use that documentation to help users.

## What is a Claude Code Skill?

A Claude Code Skill is a modular capability that extends Claude's functionality. Skills contain instructions and supporting materials that Claude can automatically discover and use based on user requests.

## How It Works

1. **Extracts domain name** from the URL (e.g., `phantombuster`, `n8n`, `getsuperapp`)
2. **Scrapes** all pages from a documentation website
3. **Converts** HTML to clean Markdown format
4. **Cleans playful URLs** using LLM (e.g., `getsuperapp` → `superapp`)
5. **Creates skill name** with `use-` prefix (e.g., `use-phantombuster`, `use-n8n`)
6. **Generates** a SKILL.md file using an LLM that tells Claude how to use the docs
7. **Creates** a ready-to-use skill folder with all documentation

The result is a lightweight RAG system that uses grep-based search instead of vector databases - perfect for technical documentation where exact term matching works well.

### Smart URL Cleaning

Docs2Skill uses a simple but effective naming strategy:

1. **URL Parsing**: Extracts the domain name from the URL (between subdomains and TLD)
   - `https://hub.phantombuster.com/reference` → `phantombuster`
   - `https://docs.n8n.io/` → `n8n`
   - `www.getsuperapp.io/docs` → `getsuperapp`

2. **LLM Cleanup** (only for playful URLs): If the domain contains marketing prefixes like "get", "try", "my", the LLM removes them
   - `getsuperapp` → `superapp`
   - `phantombuster` → `phantombuster` (no change needed)
   - `n8n` → `n8n` (no change needed)

3. **Final Naming**: Adds `use-` prefix to create the skill name (used for both folder and YAML)
   - `superapp` → `use-superapp`
   - `phantombuster` → `use-phantombuster`
   - `n8n` → `use-n8n`

Everything stays lowercase with hyphens, following Claude Code skill naming conventions.

## Features

- 🔄 **Auto-dependency installation** - No manual pip install needed
- 🌐 **Universal LLM support** - Works with Anthropic Claude, OpenAI GPT, Google Gemini, xAI Grok, OpenRouter, and local models via Ollama (Mistral, DeepSeek, Qwen, Llama, and more)
- 🎯 **Smart domain filtering** - Only scrapes same-domain links by default
- 📁 **Smart folder naming** - URL parsing + LLM cleanup for playful URLs, with `use-` prefix (e.g., `use-phantombuster`, `use-n8n`)
- 📄 **Descriptive filenames** - Uses multiple URL path segments for better discoverability (e.g., `api-authentication` not just `authentication`)
- 📊 **Progress tracking** - Visual progress bar for large scrapes
- 🤖 **Automated SKILL.md generation** - LLM creates optimized instructions following Claude Code best practices (500-line limit, table of contents for long files)
- ♻️ **Graceful fallback** - Works without LLM config (skips SKILL.md generation)

## Installation

No installation needed! Just clone and run:

```bash
git clone https://github.com/jcharovsky/Docs2Skill.git
cd Docs2Skill
```

The script auto-installs all required dependencies on first run.

## Configuration

### 1. Set up your LLM API credentials

```bash
# Copy the example config
cp .env.example .env

# Edit .env with your preferred editor
nano .env
```

### 2. Configure your LLM settings in `.env`

```env
# Choose your provider
# Options: 'anthropic', 'openai', 'gemini', 'grok', 'openrouter', 'ollama'
LLM_PROVIDER=anthropic

# Add your API key (not required for Ollama)
LLM_API_KEY=your_api_key_here

# Specify the model
LLM_MODEL=claude-3-5-sonnet-20241022

# Optional: Custom endpoint (uses defaults if not specified)
# LLM_ENDPOINT=
```

### Supported Providers & Models:

#### **Anthropic Claude** 🤖
- Models: `claude-3-5-sonnet-20241022`, `claude-3-5-sonnet-20240620`, `claude-3-opus-20240229`, `claude-3-sonnet-20240229`, `claude-3-haiku-20240307`
- Get API key: https://console.anthropic.com/

#### **OpenAI GPT** 🧠
- Models: `gpt-4`, `gpt-4-turbo`, `gpt-4o`, `gpt-4o-mini`, `gpt-3.5-turbo`, `gpt-3.5-turbo-16k`
- Get API key: https://platform.openai.com/api-keys

#### **Google Gemini** ✨
- Models: `gemini-2.0-flash-exp`, `gemini-1.5-pro`, `gemini-1.5-flash`, `gemini-1.0-pro`
- Get API key: https://makersuite.google.com/app/apikey

#### **xAI Grok** ⚡
- Models: `grok-beta`, `grok-2-1212`, `grok-2-vision-1212`
- Get API key: https://console.x.ai

#### **OpenRouter** 🌐
- Models: Access to hundreds of models from multiple providers
  - `anthropic/claude-3.5-sonnet`, `openai/gpt-4`, `google/gemini-pro`
  - `meta-llama/llama-3-70b-instruct`, `mistralai/mixtral-8x7b-instruct`
  - See full list: https://openrouter.ai/models
- Get API key: https://openrouter.ai/keys

#### **Ollama (Local)** 🏠
- Models: Run open-source models locally
  - **Llama**: `llama3`, `llama3:70b`, `llama2`
  - **Mistral**: `mistral`, `mixtral`, `mistral-openorca`
  - **DeepSeek**: `deepseek-coder`, `deepseek-coder:33b`
  - **Qwen**: `qwen`, `qwen:14b`, `qwen:72b`
  - **Others**: `phi`, `gemma`, `neural-chat`, `starling-lm`, `codellama`
  - See full library: https://ollama.com/library
- Setup: Install from https://ollama.com/download (no API key needed)

## Usage

### Basic Usage

```bash
python3 docs2skill.py https://docs.example.com
```

This will:
1. Extract the domain name from the URL
2. Scrape all pages from the same domain
3. Convert HTML to Markdown and save to a temporary folder
4. Clean playful URLs with LLM if needed
5. Create final skill folder with `use-` prefix (e.g., `../use-phantombuster/`)
6. Generate a `SKILL.md` file using your configured LLM

The skill folder is created as a sibling to Docs2Skill, keeping the tool directory clean.

### Advanced Options

**Scrape all domains** (including external links):
```bash
python3 docs2skill.py https://docs.example.com --all-domains
```

**Custom output folder**:
```bash
python3 docs2skill.py https://docs.example.com -o my_custom_folder
```

**Skip LLM generation** (just scrape docs):
```bash
# Simply don't configure .env - script will skip SKILL.md generation
python3 docs2skill.py https://docs.example.com
```

## Output Structure

After running the script from inside the Docs2Skill folder, you'll get:

```
parent/
├── Docs2Skill/                       # Tool directory (stays clean)
│   ├── docs2skill.py
│   ├── .env
│   └── README.md
└── use-phantombuster/                # Generated skill (with use- prefix)
    ├── SKILL.md                      # LLM-generated skill instructions
    └── resources/                    # Supporting documentation
        ├── agents-fetch-output.md    # Descriptive multi-segment names
        ├── api-authentication.md
        ├── getting-started-quickstart.md
        └── ... (more documentation files)
```

## Deploying Generated Skills

Once Docs2Skill generates your skill folder, you can deploy it to any Claude platform. **Note:** Skills don't sync across platforms—you must deploy separately to each one you want to use.

### Deployment Options:

#### 🖥️ **Claude Code (CLI)**
Deploy to your local Claude Code installation for terminal-based development.

**Personal skills** (available in all projects):
```bash
cp -r ../use-phantombuster ~/.claude/skills/
```

**Project skills** (shared with team via git):
```bash
cp -r ../use-phantombuster .claude/skills/
```

📚 **Full guide:** [Claude Code Skills Documentation](https://docs.claude.com/en/docs/claude-code/skills)

---

#### 🌐 **Claude.ai & Claude Desktop**
Upload your skill as a ZIP file through the web interface or desktop app.

**Steps:**
1. ZIP your skill folder: `zip -r use-phantombuster.zip use-phantombuster/`
2. Go to **Settings > Features** on Claude.ai or Claude Desktop
3. Upload the ZIP file
4. Enable in **Settings > Capabilities**

📚 **Full guide:** [How to Create Custom Skills](https://support.claude.com/en/articles/12512198-how-to-create-custom-skills)

---

#### 🤖 **Claude Agent SDK**
Use skills in agent workflows by placing them in your project's `.claude/skills/` directory.

**Setup:**
```bash
cp -r ../use-phantombuster /path/to/your-project/.claude/skills/
```

Enable in your SDK configuration:
```python
allowed_tools=["Skill", ...]
```

📚 **Full guide:** [Agent SDK Skills](https://docs.claude.com/en/api/agent-sdk/skills)

---

#### 🔌 **Claude API**
Upload custom skills via API for programmatic access.

**Upload skill:**
```bash
curl https://api.anthropic.com/v1/skills \
  -H "x-api-key: $ANTHROPIC_API_KEY" \
  -H "anthropic-version: 2023-06-01" \
  -F "file=@use-phantombuster.zip"
```

**Use in Messages API:**
```python
container = {
    "skills": [{
        "type": "custom",
        "skill_id": "skill_01AbCdEfGhIjKlMnOpQrStUv"
    }]
}
```

📚 **Full guide:** [API Skills Guide](https://docs.claude.com/en/api/skills-guide)

---

### How Skills Work

Once deployed, Claude automatically discovers and activates skills when relevant:

1. **Matches** the skill description to user queries
2. **Searches** through resources/ markdown files using grep
3. **Reads** relevant documentation
4. **Provides** accurate answers with examples

**Example:**
```
User: "How do I authenticate with the Phantombuster API?"

Claude: [Activates use-phantombuster skill]
        [Searches resources/*.md for "authentication"]
        [Reads resources/authentication.md]
        [Provides answer with code examples]
```

## How SKILL.md Works

The generated SKILL.md contains:

1. **YAML Frontmatter** - Skill name (with `use-` prefix), description for discovery, version (1.0.0), and optional dependencies
2. **Instructions** - How Claude should use the documentation in resources/
3. **Examples** - Sample questions and interaction patterns

It acts as **meta-instructions** for Claude, telling it:
- When to activate this skill
- How to search the supporting .md files in the resources/ folder
- What kinds of questions to expect
- Best practices for answering

## Claude Code Best Practices

Docs2Skill implements best practices from the official Claude Code documentation:

- [Skills Announcement](https://www.anthropic.com/news/skills)
- [How to Create Custom Skills](https://support.claude.com/en/articles/12512198-how-to-create-custom-skills)
- [Agent Skills Overview](https://docs.claude.com/en/docs/agents-and-tools/agent-skills/overview)
- [Agent Skills Quickstart](https://docs.claude.com/en/docs/agents-and-tools/agent-skills/quickstart)
- [Agent Skills Best Practices](https://docs.claude.com/en/docs/agents-and-tools/agent-skills/best-practices)

### YAML & Structure

Generated skills follow all official requirements:

- **Name validation**: Lowercase only, max 64 characters, no reserved words ("anthropic", "claude"), no XML tags
- **Description format**: Max 1024 characters, written in third person, includes specific trigger terms, no XML tags
- **Version field**: Semantic versioning (1.0.0) for tracking iterations
- **Dependencies field**: Optional, documents required packages if applicable
- **500-line body limit**: Keeps SKILL.md under 500 lines for optimal performance
- **Progressive disclosure**: Main content in SKILL.md, detailed content in resources/
- **One-level-deep references**: All resource files link directly from SKILL.md (no nested chains)
- **Table of contents**: Auto-generated for resource files over 100 lines

### Content Quality

The LLM generates high-quality, maintainable skills:

- **Consistent terminology**: Uses the same term throughout (e.g., always "API endpoint", never mixed with "URL")
- **No time-sensitive info**: Avoids dates and version cutoffs; uses "Old patterns" sections for deprecated approaches
- **Clear defaults**: Provides default recommendations when multiple options exist
- **Concrete examples**: Includes 2-3 example interactions showing typical usage
- **Concise instructions**: Assumes Claude is intelligent; only adds context Claude lacks

### Technical Details

- **Descriptive filenames**: Uses multiple URL path segments (e.g., `api-authentication.md`, `getting-started-quickstart.md`)
- **Forward slashes**: All file paths use forward slashes for cross-platform compatibility
- **Naming conventions**: Uses `use-` prefix (e.g., `use-phantombuster`, `use-n8n`)

## Requirements

All dependencies are auto-installed on first run:
- `requests` - HTTP requests
- `beautifulsoup4` - HTML parsing
- `html2text` - HTML to Markdown conversion
- `python-dotenv` - Environment variable management
- `tqdm` - Progress bars

## Troubleshooting

### "LLM_API_KEY not found"
Make sure you've created a `.env` file (not `.env.example`) and added your API key.

### "No links found"
The starting URL might not have any links, or the page failed to load. Check the URL and try again.

### Progress bar not showing
The script may be processing - give it a moment. For very small sites, the progress bar appears briefly.

### LLM generation fails
- Check your API key is valid
- Verify your account has credits/quota
- Check the model name is correct for your provider

## Examples

### Scrape Phantombuster Documentation
```bash
cd Docs2Skill
python3 docs2skill.py https://hub.phantombuster.com/reference
```

Output: `../use-phantombuster/` folder with SKILL.md + resources/ containing all API docs

### Scrape Brightdata Docs
```bash
cd Docs2Skill
python3 docs2skill.py https://docs.brightdata.com
```

Output: `../use-brightdata/` folder with SKILL.md + resources/ containing all docs

### Scrape n8n Documentation
```bash
cd Docs2Skill
python3 docs2skill.py https://docs.n8n.io
```

Output: `../use-n8n/` folder with SKILL.md + resources/ containing all docs

### Scrape from Playful URL
```bash
cd Docs2Skill
python3 docs2skill.py https://www.getsuperapp.io/docs
```

Output: `../use-superapp/` folder (automatically cleaned from "getsuperapp")

## Architecture

Docs2Skill implements a **grep-based RAG system**:

**Traditional RAG:**
- Chunks → Embeddings → Vector DB → Semantic Search → LLM

**Docs2Skill:**
- Markdown files → Grep search → Read files → LLM

This approach:
- ✅ Zero infrastructure (no vector DB needed)
- ✅ Works great for technical docs (exact term matching)
- ✅ Instant setup (no preprocessing/embedding)
- ✅ Easy to inspect and debug (just text files)

## Contributing

Contributions welcome! This is an open-source project.

## License

MIT License - see [LICENSE](LICENSE) file for details

## Credits

Built for the Claude Code community to make documentation more accessible and queryable.

---

**Have questions or issues?** Open an issue on GitHub!

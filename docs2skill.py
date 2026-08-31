#!/usr/bin/env python3
"""
Markdown Scraper - Scrapes HTML content and converts to Markdown from all sub-URLs
"""

import argparse
from fnmatch import fnmatch
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlparse

import html2text
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from tqdm import tqdm

# LLM Configuration
class LLMConfig:
    """Configuration for LLM API calls"""

    PROVIDER_DEFAULTS = {
        'anthropic': 'https://api.anthropic.com/v1/messages',
        'openai': 'https://api.openai.com/v1/chat/completions',
        'openrouter': 'https://openrouter.ai/api/v1/chat/completions',
        'gemini': 'https://generativelanguage.googleapis.com/v1beta/models/',
        'grok': 'https://api.x.ai/v1/chat/completions',
        'ollama': 'http://localhost:11434/v1/chat/completions'
    }

    def __init__(self):
        self.provider = os.getenv('LLM_PROVIDER', 'anthropic').lower()
        self.api_key = os.getenv('LLM_API_KEY', '')
        self.model = os.getenv('LLM_MODEL', 'claude-3-5-sonnet-20241022')
        self.endpoint = os.getenv('LLM_ENDPOINT', '') or self.PROVIDER_DEFAULTS.get(self.provider, '')

    def validate(self):
        """Validate configuration"""
        if not self.api_key:
            raise ValueError(
                "LLM_API_KEY not found. Please create a .env file with your API key.\n"
                "See env.example for template."
            )
        if self.provider not in self.PROVIDER_DEFAULTS:
            print(f"Warning: Unknown provider '{self.provider}'. Supported: {list(self.PROVIDER_DEFAULTS.keys())}")
        if not self.endpoint:
            raise ValueError(f"No endpoint configured for provider '{self.provider}'")
        return True


# System prompt for SKILL.md generation
CLAUDE_SKILL_GENERATION_PROMPT = """You are an expert at creating Claude Code Skills based on documentation.

Your task is to create a SKILL.md file that enables Claude to effectively use the provided documentation to help users.

## SKILL.md Structure Requirements:

1. **YAML Frontmatter** (only required fields - do NOT include any other fields):
```yaml
---
name: skill-name-here
description: |
  Brief description of what this skill does and when Claude should use it.
  One concise sentence that front-loads the product and trigger terms. Max 300 characters.
---
```

Note: Only `name` and `description` are allowed. Do NOT include `version`, `dependencies`, or any other fields not listed here.

2. **Name Requirements**:
   - Lowercase only
   - Max 64 characters
   - Use hyphens for spaces (e.g., "use-phantombuster")
   - Should reflect the domain/service
   - **CRITICAL**: Cannot contain reserved words: "anthropic" or "claude"
   - **CRITICAL**: Cannot contain XML tags

3. **Description Requirements** (CRITICAL):
   - Maximum 300 characters
   - Use one concise sentence that front-loads the product and key use cases
   - Explain BOTH what the skill does AND when to use it
   - Include specific trigger terms (product names, API names, service names)
   - Be concrete, not generic
   - Examples of good descriptions:
     * "Expert assistance with Phantombuster API automation. Use when user asks about Phantombuster agents, API endpoints, automation workflows, or web scraping with Phantombuster."
     * "Brightdata proxy and web scraping documentation. Use when user needs help with Brightdata proxies, SERP APIs, web unlocker, or data collection services."
   - Avoid generic descriptions like "Documentation helper" or "API reference"
   - **CRITICAL**: Cannot contain XML tags

4. **Instructions Section**:
   - **CRITICAL**: Keep SKILL.md body under 500 lines for optimal performance
   - Provide step-by-step guidance for Claude
   - Explain how to search/use the supporting markdown files in the resources/ subdirectory
   - Include best practices for answering user questions
   - Mention that Claude should search and read relevant .md files from resources/ to find accurate information
   - Resource files over 100 lines include a generated contents section. Tell Claude to use it and search before reading narrow ranges.
   - Use progressive disclosure: keep SKILL.md as overview, detailed content goes in resources/
   - **IMPORTANT**: Keep file references one level deep - all files should link directly from SKILL.md, not from other resource files
   - **IMPORTANT**: Avoid time-sensitive information (no dates, version cutoffs). Use "Old patterns" sections for deprecated approaches instead
   - **IMPORTANT**: When multiple approaches exist, provide a clear default recommendation rather than listing many equivalent options
   - **IMPORTANT**: Use consistent terminology throughout - choose one term and stick with it (e.g., always "API endpoint", never mix with "URL" or "route")

5. **Examples Section**:
   - Provide 2-3 example interactions
   - Show what kinds of questions users might ask
   - Demonstrate how Claude should respond
   - Ground every example in the supplied documentation
   - An MCP example must name at least one exact tool from the documented MCP tool inventory

6. **Key Principles**:
   - Focus on ONE specific capability/service
   - Make descriptions discoverable (include terms users will actually use)
   - Keep instructions clear and actionable (under 500 lines total)
   - Reference the supporting documentation files in the resources/ subdirectory
   - Assume Claude is already intelligent; only add context it lacks

## Your Task:

You will receive:
- An extracted domain name from the URL (e.g., "getsuperapp", "phantombuster", "n8n")
- A source URL
- A list of markdown filenames that contain the scraped documentation

**IMPORTANT**: All supporting documentation files are located in a `resources/` subdirectory (lowercase).
In your instructions, tell Claude to search and read files from the `resources/` folder.

## Output Format:

You MUST respond with a JSON object containing two fields:
```json
{
  "cleaned_name": "productname",
  "skill_content": "---\nname: use-productname\n..."
}
```

1. **cleaned_name**: The actual product name, cleaned from playful URL patterns:
   - If the extracted name has marketing prefixes like "get", "try", "use", "my", remove them
   - Examples: "getsuperapp" → "superapp", "trynotion" → "notion", "mystripe" → "stripe"
   - If the name is already clean, return it as-is: "phantombuster" → "phantombuster", "n8n" → "n8n"
   - ALWAYS lowercase, no capitalization whatsoever
   - No hyphens or spaces, just the clean product name

2. **skill_content**: A complete SKILL.md file that:
   - Has proper YAML frontmatter with ONLY these fields:
     * `name: use-{cleaned_name}` (e.g., "use-phantombuster", "use-n8n")
     * `description` in third person with specific trigger terms
     * DO NOT include any other fields like `version`, `dependencies`, etc.
   - Provides clear instructions for Claude on how to use the documentation in resources/
   - Includes relevant examples
   - Uses forward slashes for all file paths (e.g., resources/guide.md)
   - Uses complete resource paths from the supplied file list. Exact file references start with `resources/`. Search patterns may use matching `resources/...*.md` globs.
   - When MCP documentation is present, includes MCP in the description, names its exact resource path, and distinguishes documentation from live tools for current state and requested operations.
   - Follows all best practices above

Output ONLY valid JSON with these two fields, nothing else."""


CODEX_SKILL_GENERATION_PROMPT = """You are an expert at creating Codex skills based on documentation.

Your task is to create a complete, Codex-compatible SKILL.md file that enables Codex to answer users accurately from the provided documentation.

## SKILL.md requirements

1. Begin the file with YAML frontmatter delimited by `---` lines.
2. Include these required frontmatter fields:
   - `name`: lowercase letters, numbers, and hyphens only, at most 64 characters.
   - `description`: one concise sentence that front-loads the product, key use cases, and trigger terms. Keep it at most 300 characters.
3. Name the skill `use-{cleaned_name}`.
4. Keep the body concise and actionable. It must explain how Codex should identify and read relevant Markdown files in `resources/` before answering.
5. Use progressive disclosure. Keep detailed documentation in `resources/`, and reference files directly from SKILL.md with forward-slash paths.
6. Give a clear default when multiple approaches exist, use consistent terminology, and distinguish deprecated patterns when the documentation does.
7. Include two or three brief example user requests. Ground every example in the supplied documentation. An MCP example must name at least one exact tool from the documented MCP tool inventory. When no inventory is supplied, use examples from other documented interfaces. Do not include Claude Code, Claude.ai, Anthropic, or deployment instructions.
8. Tell Codex to search filenames and contents with `rg`, consult generated contents sections, and read narrow ranges instead of loading large resources in full.
9. Include distinct documented interfaces such as APIs, SDKs, CLIs, or MCP servers in the description and routing when they appear in the filenames or sample content.
10. Use complete resource paths. Exact file references must use `resources/<filename>.md`. Search patterns may use matching `resources/...*.md` globs. Never use bare, shortened, or invented filenames.
11. When MCP documentation is present, include MCP in the description, link its exact resource path, and distinguish documentation from live MCP tools. Documentation explains behavior. Available MCP tools provide current service state and perform user-requested operations.
12. When a generation focus is supplied, prioritize matching resources and capabilities in routing and examples. Include the focus only when the supplied documentation supports it.

## Source material

You will receive an extracted domain name, the source URL, and a list of Markdown files in `resources/`. The content of those resource files is shared with the Claude Code target. Do not add, rename, or refer to files outside `resources/`.

## Output format

Respond only with this valid JSON object:
```json
{
  "cleaned_name": "productname",
  "skill_content": "---\\nname: use-productname\\ndescription: |\\n  ...\\n---\\n..."
}
```

`cleaned_name` must be lowercase and contain no spaces or hyphens. Remove marketing prefixes such as `get`, `try`, `use`, or `my` when they are present. Keep an already-clean product name unchanged."""


SKILL_GENERATION_PROMPTS = {
    'claude': CLAUDE_SKILL_GENERATION_PROMPT,
    'codex': CODEX_SKILL_GENERATION_PROMPT,
}


def call_llm(config, system_prompt, user_message):
    """Call LLM API based on provider"""
    if config.provider == 'anthropic':
        return call_anthropic(config, system_prompt, user_message)
    elif config.provider == 'gemini':
        return call_gemini(config, system_prompt, user_message)
    elif config.provider in ['openai', 'openrouter', 'grok', 'ollama']:
        return call_openai_compatible(config, system_prompt, user_message)
    else:
        raise ValueError(f"Unsupported provider: {config.provider}")


def call_anthropic(config, system_prompt, user_message):
    """Call Anthropic Messages API"""
    headers = {
        'x-api-key': config.api_key,
        'anthropic-version': '2023-06-01',
        'content-type': 'application/json'
    }

    payload = {
        'model': config.model,
        'max_tokens': 4096,
        'temperature': 0.7,
        'system': system_prompt,
        'messages': [
            {
                'role': 'user',
                'content': user_message
            }
        ]
    }

    response = requests.post(config.endpoint, headers=headers, json=payload, timeout=60)
    response.raise_for_status()
    result = response.json()

    return result['content'][0]['text']


def call_openai_compatible(config, system_prompt, user_message):
    """Call OpenAI-compatible API (OpenAI, OpenRouter, Grok, Ollama, etc.)"""
    headers = {
        'Content-Type': 'application/json'
    }

    # Add API key header (Ollama doesn't require it, others do)
    if config.provider != 'ollama':
        headers['Authorization'] = f'Bearer {config.api_key}'

    # OpenRouter requires HTTP-Referer header
    if config.provider == 'openrouter':
        headers['HTTP-Referer'] = 'https://github.com/jcharovsky/Docs2Skill'

    payload = {
        'model': config.model,
        'max_tokens': 4096,
        'temperature': 0.7,
        'messages': [
            {
                'role': 'system',
                'content': system_prompt
            },
            {
                'role': 'user',
                'content': user_message
            }
        ]
    }

    response = requests.post(config.endpoint, headers=headers, json=payload, timeout=60)
    response.raise_for_status()
    result = response.json()

    return result['choices'][0]['message']['content']


def call_gemini(config, system_prompt, user_message):
    """Call Google Gemini API"""
    # Gemini endpoint format: {base_url}{model}:generateContent
    # If config.endpoint ends with '/', it's the base URL
    if config.endpoint.endswith('/'):
        endpoint = f"{config.endpoint}{config.model}:generateContent"
    else:
        endpoint = config.endpoint

    headers = {
        'x-goog-api-key': config.api_key,
        'Content-Type': 'application/json'
    }

    # Gemini uses a different format: contents with parts
    payload = {
        'contents': [
            {
                'parts': [
                    {
                        'text': f"{system_prompt}\n\n{user_message}"
                    }
                ]
            }
        ],
        'generationConfig': {
            'temperature': 0.7,
            'maxOutputTokens': 4096
        }
    }

    response = requests.post(endpoint, headers=headers, json=payload, timeout=60)
    response.raise_for_status()
    result = response.json()

    # Gemini response format: candidates[0].content.parts[0].text
    return result['candidates'][0]['content']['parts'][0]['text']


def normalize_url(url):
    """Remove fragments that do not affect the HTTP resource."""
    return urldefrag(url).url


def get_all_links(url):
    """Extract all links from a webpage"""
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')

        links = set()
        for link in soup.find_all('a', href=True):
            absolute_url = urljoin(url, link['href'])
            links.add(normalize_url(absolute_url))

        return links
    except Exception as e:
        print(f"Error fetching {url}: {e}", file=sys.stderr)
        return set()


def get_domain_name(url):
    """Extract the main domain name from URL (e.g., 'phantombuster' from 'https://hub.phantombuster.com')"""
    parsed = urlparse(url)
    domain = parsed.netloc

    # Remove port if present
    domain = domain.split(':')[0]

    # Split by dots
    parts = domain.split('.')

    # Remove common subdomains (www, docs, api, etc.) and get the main domain
    # If we have something like docs.brightdata.com, we want 'brightdata'
    # If we have brightdata.com, we want 'brightdata'
    if len(parts) >= 2:
        # Get the second-to-last part (the main domain before the TLD)
        domain_name = parts[-2]
    else:
        domain_name = parts[0]

    return domain_name.lower()


def get_default_output_dir(skill_type, extracted_name):
    """Return the target's personal skills directory for the current user."""
    skills_directory = '.agents' if skill_type == 'codex' else '.claude'
    return str(Path.home() / skills_directory / 'skills' / extracted_name)


def get_filename_from_url(url):
    """
    Extract descriptive filename from URL path.
    Uses last 2-3 path segments to create more descriptive names.
    Example: /api/v1/authentication -> api-v1-authentication
    """
    parsed = urlparse(url)
    path = parsed.path.strip('/')

    # If empty, use 'index'
    if not path:
        return 'index'

    # Split path into segments
    segments = path.split('/')

    # Remove common documentation prefixes that don't add value
    skip_prefixes = ['docs', 'documentation', 'reference', 'guide', 'api-reference', 'en', 'v1', 'v2', 'v3']
    segments = [s for s in segments if s.lower() not in skip_prefixes]

    # If we filtered everything, use the original last segment
    if not segments:
        segments = path.split('/')[-1:]

    # Take last 2-3 segments for better context (but not too long)
    # Example: /getting-started/installation/windows -> getting-started-installation-windows
    max_segments = 3
    if len(segments) > max_segments:
        segments = segments[-max_segments:]

    # Join segments with hyphens
    filename = '-'.join(segments)

    # Remove any file extensions that might be in the URL
    filename = re.sub(r'\.(html|htm|php|asp|aspx)$', '', filename, flags=re.IGNORECASE)

    # Sanitize the filename (replace special characters with hyphens)
    filename = re.sub(r'[^\w\-]', '-', filename)

    # Remove multiple consecutive hyphens
    filename = re.sub(r'-+', '-', filename)

    # Remove leading/trailing hyphens
    filename = filename.strip('-')

    # Limit filename length (keep it reasonable)
    if len(filename) > 100:
        # Try to cut at a hyphen boundary
        filename = filename[:100]
        last_hyphen = filename.rfind('-')
        if last_hyphen > 50:  # Only cut at hyphen if it's not too early
            filename = filename[:last_hyphen]

    return filename or 'page'


MARKDOWN_CHROME_PATTERNS = (
    re.compile(r'Skip to content'),
    re.compile(r'!\[\]\([^)]*sidebar-rail-collapse\.svg\) Press Arrow down .+'),
    re.compile(r'Press `Esc` to close the menu'),
    re.compile(r'\[ BRAZE SYSTEM STATUS Checking Braze Status \]\(https://braze\.statuspage\.io/?\)'),
    re.compile(r'__ Copy for LLM __ View as Markdown __ Build with an LLM'),
    re.compile(r'New Stuff!'),
    re.compile(r'__ Back to top'),
)


def remove_markdown_chrome(markdown):
    """Remove known documentation controls left by HTML-to-Markdown conversion."""
    lines = [
        line for line in markdown.splitlines()
        if not any(pattern.fullmatch(line.strip()) for pattern in MARKDOWN_CHROME_PATTERNS)
    ]
    return '\n'.join(lines).strip()


def convert_html_to_markdown(html_content):
    """Convert HTML content to Markdown format"""
    # Parse HTML
    soup = BeautifulSoup(html_content, 'html.parser')

    # Remove unwanted elements
    for element in soup(['script', 'style', 'nav', 'footer', 'header', 'iframe', 'noscript']):
        element.decompose()

    # Remove common documentation controls that sit outside semantic HTML tags.
    chrome_selectors = (
        '.skip-main',
        '.sr-only',
        '[role="navigation"]',
        '#nav_bar',
        '.copy-for-llm-page-header',
        '#cc_prompt',
    )
    for selector in chrome_selectors:
        for element in soup.select(selector):
            element.decompose()

    # Get the cleaned HTML
    cleaned_html = str(soup)

    # Configure html2text
    h = html2text.HTML2Text()
    h.ignore_links = False
    h.ignore_images = False
    h.ignore_emphasis = False
    h.body_width = 0  # Don't wrap text
    h.single_line_break = False

    # Convert to markdown
    markdown = remove_markdown_chrome(h.handle(cleaned_html))

    return markdown.strip()


def scrape_url(url, output_dir):
    """Scrape HTML content and convert to Markdown"""
    try:
        url = normalize_url(url)
        response = requests.get(url, timeout=10)
        response.raise_for_status()

        # Check if it's HTML content
        content_type = response.headers.get('content-type', '').lower()
        if 'html' not in content_type:
            tqdm.write(f"⊘ Skipped (not HTML): {url}")
            return False

        # Convert HTML to Markdown
        markdown_content = convert_html_to_markdown(response.content)

        if not markdown_content.strip():
            tqdm.write(f"⊘ Skipped (no content): {url}")
            return False

        # Create resources subdirectory
        resources_dir = os.path.join(output_dir, 'resources')
        os.makedirs(resources_dir, exist_ok=True)

        # Create filename from URL path
        filename = get_filename_from_url(url) + '.md'
        filepath = os.path.join(resources_dir, filename)

        # Handle duplicate filenames
        counter = 1
        original_filepath = filepath
        while os.path.exists(filepath):
            name, ext = os.path.splitext(original_filepath)
            filepath = f"{name}_{counter}{ext}"
            counter += 1

        # Save markdown content with URL metadata
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(f"# {get_filename_from_url(url)}\n\n")
            f.write(f"**Source URL:** {url}\n\n")
            f.write("---\n\n")
            f.write(markdown_content)

        tqdm.write(f"✓ Scraped: {url} -> {os.path.basename(filepath)}")
        return True
    except Exception as e:
        tqdm.write(f"✗ Failed to scrape {url}: {e}")
        return False


def get_grouping_key_from_url(url):
    """
    Extract grouping key from URL based on path depth.
    - URLs with 0-3 path segments: return full path (each gets own file)
    - URLs with 4+ path segments: return first 3 segments (merged together)

    Examples:
        https://docs.n8n.io/ -> ''
        https://docs.n8n.io/integrations/ -> 'integrations'
        https://docs.n8n.io/integrations/builtin/ -> 'integrations/builtin'
        https://docs.n8n.io/integrations/builtin/core-nodes/ -> 'integrations/builtin/core-nodes'
        https://docs.n8n.io/integrations/builtin/core-nodes/httpRequest/ -> 'integrations/builtin/core-nodes' (grouped)
        https://docs.n8n.io/integrations/builtin/core-nodes/webHook/ -> 'integrations/builtin/core-nodes' (grouped)
    """
    parsed = urlparse(url)
    path = parsed.path.strip('/')

    if not path:
        return 'index'

    segments = path.split('/')

    # If 3 or fewer segments, use full path (each gets own file)
    if len(segments) <= 3:
        return path

    # If 4 or more segments, use only first 3 (merge together)
    return '/'.join(segments[:3])


def group_and_merge_files(output_dir):
    """
    Group and merge markdown files based on URL path depth.
    Files from URLs with 4+ path segments are merged based on first 3 segments.
    """
    resources_dir = os.path.join(output_dir, 'resources')

    if not os.path.exists(resources_dir):
        return

    print("\n" + "="*60)
    print("Grouping and merging files...")
    print("="*60)

    # Read all files and extract their source URLs
    file_data = {}  # {filepath: (url, content)}

    for filename in os.listdir(resources_dir):
        if not filename.endswith('.md'):
            continue

        filepath = os.path.join(resources_dir, filename)
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()

            # Extract source URL from file (it's in the format: **Source URL:** {url})
            url_match = re.search(r'\*\*Source URL:\*\*\s+(.+)', content)
            if url_match:
                source_url = url_match.group(1).strip()
                file_data[filepath] = (source_url, content)
        except Exception as e:
            print(f"Warning: Could not read {filename}: {e}")

    # Group files by their grouping key
    groups = {}  # {grouping_key: [(url, content), ...]}

    for filepath, (url, content) in file_data.items():
        grouping_key = get_grouping_key_from_url(url)
        if grouping_key not in groups:
            groups[grouping_key] = []
        groups[grouping_key].append((url, content, filepath))

    # Process each group
    files_before = len(file_data)
    files_after = 0
    merged_count = 0

    for grouping_key, items in groups.items():
        # Create filename from grouping key
        grouped_filename = grouping_key.replace('/', '-') + '.md'
        if grouped_filename == '.md':
            grouped_filename = 'index.md'

        grouped_filepath = os.path.join(resources_dir, grouped_filename)

        if len(items) == 1:
            # Single file - check if it needs renaming to match grouping key
            url, content, original_filepath = items[0]
            original_filename = os.path.basename(original_filepath)

            if original_filename != grouped_filename and original_filepath != grouped_filepath:
                # Rename to match grouping key (if not already named correctly)
                if not os.path.exists(grouped_filepath):
                    os.rename(original_filepath, grouped_filepath)
                    print(f"  Renamed: {original_filename} -> {grouped_filename}")
                else:
                    print(f"  Warning: Target file {grouped_filename} already exists, keeping {original_filename}")

            files_after += 1
        else:
            # Multiple files - merge them
            merged_content_parts = []

            # Sort items by URL for consistent ordering
            items.sort(key=lambda x: x[0])

            for url, content, _ in items:
                # Extract just the content (skip the header we added)
                # Content format: # title\n\n**Source URL:** url\n\n---\n\ncontent
                content_lines = content.split('\n')

                # Find where actual content starts (after the --- separator)
                content_start_idx = 0
                for i, line in enumerate(content_lines):
                    if line.strip() == '---':
                        content_start_idx = i + 1
                        break

                actual_content = '\n'.join(content_lines[content_start_idx:]).strip()

                # Create section with URL as header
                parsed = urlparse(url)
                path = parsed.path.strip('/')
                section_title = path.split('/')[-1] or 'Home'
                section_title = section_title.replace('-', ' ').title()

                merged_content_parts.append(f"## {section_title}\n\n**Source:** {url}\n\n{actual_content}")

            # Create merged file with a title
            group_title = grouping_key.replace('/', ' - ').replace('-', ' ').title()
            if group_title == 'Index':
                group_title = 'Home'

            merged_content = f"# {group_title}\n\n" + "\n\n---\n\n".join(merged_content_parts)

            # Save merged file
            with open(grouped_filepath, 'w', encoding='utf-8') as f:
                f.write(merged_content)

            # Delete original files
            for _, _, original_filepath in items:
                if os.path.exists(original_filepath):
                    os.remove(original_filepath)

            merged_count += len(items)
            files_after += 1
            print(f"  Merged {len(items)} files -> {grouped_filename}")

    print(f"\n✓ Grouping complete:")
    print(f"  Files before: {files_before}")
    print(f"  Files after: {files_after}")
    print(f"  Files merged: {merged_count}")
    print(f"  Reduction: {files_before - files_after} files")


MERGED_SECTION_PATTERN = re.compile(
    r'^##\s+(.+?)\n\n\*\*Source:\*\*\s+(https?://\S+)\s*$',
    re.MULTILINE
)
CONTENTS_START = '<!-- docs2skill-contents:start -->'
CONTENTS_END = '<!-- docs2skill-contents:end -->'


def deduplicate_merged_sections(content):
    """Remove repeated merged sections that resolve to the same URL."""
    matches = list(MERGED_SECTION_PATTERN.finditer(content))
    if len(matches) < 2:
        return content

    prefix = content[:matches[0].start()].rstrip()
    sections = []
    seen_urls = set()
    seen_bodies = set()

    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        section = content[match.start():end].strip()
        section = re.sub(r'\n+---\s*$', '', section).rstrip()
        source_url = normalize_url(match.group(2))
        body_start = match.end() - match.start()
        section_body = section[body_start:].strip()

        if source_url in seen_urls or section_body in seen_bodies:
            continue

        seen_urls.add(source_url)
        seen_bodies.add(section_body)
        section = re.sub(
            r'(\*\*Source:\*\*\s+)https?://\S+',
            lambda source_match: f'{source_match.group(1)}{source_url}',
            section,
            count=1
        )
        sections.append(section)

    return f"{prefix}\n\n" + "\n\n---\n\n".join(sections) + "\n"


def remove_generated_contents_section(content):
    """Remove a generated contents section so it can be rebuilt."""
    marked_pattern = re.compile(
        rf'\n*{re.escape(CONTENTS_START)}.*?{re.escape(CONTENTS_END)}\n*',
        re.DOTALL
    )
    if marked_pattern.search(content):
        return marked_pattern.sub('\n\n', content, count=1).strip() + '\n'

    legacy_match = re.search(r'^## Contents\s*$', content, re.MULTILINE)
    if not legacy_match or legacy_match.start() > 2000:
        return content

    next_wrapper = MERGED_SECTION_PATTERN.search(content, legacy_match.end())
    next_heading = re.search(
        r'^#{1,6}\s+.+$',
        content[legacy_match.end():],
        re.MULTILINE
    )
    next_heading_start = (
        legacy_match.end() + next_heading.start()
        if next_heading else None
    )
    candidates = [
        position for position in (
            next_wrapper.start() if next_wrapper else None,
            next_heading_start,
        )
        if position is not None
    ]
    if not candidates:
        return content

    end = min(candidates)
    return f"{content[:legacy_match.start()].rstrip()}\n\n{content[end:].lstrip()}"


def add_contents_section(content, minimum_lines=100):
    """Add a compact contents index to a long resource file."""
    content = remove_generated_contents_section(content)
    lines = content.splitlines()
    if len(lines) <= minimum_lines:
        return content

    merged_entries = [
        (match.group(1).strip(), normalize_url(match.group(2)))
        for match in MERGED_SECTION_PATTERN.finditer(content)
    ]

    if merged_entries:
        entries = [f'- {title}: {source_url}' for title, source_url in merged_entries]
    else:
        headings = [
            match.group(1).strip()
            for match in re.finditer(r'^##\s+(.+?)\s*$', content, re.MULTILINE)
            if match.group(1).strip().lower() != 'contents'
        ]
        if not headings:
            level_one_headings = [
                match.group(1).strip()
                for match in re.finditer(r'^#\s+(.+?)\s*$', content, re.MULTILINE)
            ]
            headings = level_one_headings[1:] if len(level_one_headings) > 1 else level_one_headings
        if not headings:
            link_labels = [
                re.sub(r'\s+', ' ', match.group(1)).strip()
                for match in re.finditer(r'(?<!!)\[([^\]\n]+)\]\([^)]+\)', content)
            ]
            headings = list(dict.fromkeys(label for label in link_labels if label))[:50]
        if not headings:
            headings = ['Document body']
        entries = [f'- {heading}' for heading in headings]

    contents_block = (
        f"{CONTENTS_START}\n"
        "## Contents\n\n"
        + "\n".join(entries)
        + f"\n{CONTENTS_END}"
    )

    separator_index = next(
        (index for index, line in enumerate(lines[:10]) if line.strip() == '---'),
        None
    )
    insert_at = separator_index + 1 if separator_index is not None else 1
    updated_lines = lines[:insert_at] + ['', contents_block, ''] + lines[insert_at:]
    return '\n'.join(updated_lines).strip() + '\n'


def postprocess_resource_files(output_dir):
    """Deduplicate merged sections and index long Markdown resources."""
    resources_dir = os.path.join(output_dir, 'resources')
    if not os.path.exists(resources_dir):
        return {'files_updated': 0, 'duplicates_removed': 0, 'contents_added': 0}

    stats = {'files_updated': 0, 'duplicates_removed': 0, 'contents_added': 0}

    for filename in sorted(os.listdir(resources_dir)):
        if not filename.endswith('.md'):
            continue

        filepath = os.path.join(resources_dir, filename)
        with open(filepath, 'r', encoding='utf-8') as file:
            original = file.read()

        source_count_before = len(MERGED_SECTION_PATTERN.findall(original))
        had_contents = bool(re.search(r'^## Contents\s*$', original, re.MULTILINE))
        updated = remove_markdown_chrome(original) + '\n'
        updated = deduplicate_merged_sections(updated)
        source_count_after = len(MERGED_SECTION_PATTERN.findall(updated))
        updated = add_contents_section(updated)
        has_contents = bool(re.search(r'^## Contents\s*$', updated, re.MULTILINE))

        stats['duplicates_removed'] += source_count_before - source_count_after
        if not had_contents and has_contents:
            stats['contents_added'] += 1

        if updated != original:
            with open(filepath, 'w', encoding='utf-8') as file:
                file.write(updated)
            stats['files_updated'] += 1

    print("\nResource post-processing complete:")
    print(f"  Files updated: {stats['files_updated']}")
    print(f"  Duplicate sections removed: {stats['duplicates_removed']}")
    print(f"  Contents sections added: {stats['contents_added']}")
    return stats


CONTEXT_FILE_MARKERS = (
    'mcp',
    'cli',
    'sdk',
    'compliance',
    'api',
    'developer_guide',
    'user_guide',
)
MAX_SKILL_DESCRIPTION_CHARS = 300
CONTEXT_PREFIX_CHARS = 500
CONTEXT_EXCERPT_CHARS = 2500
MCP_TABLE_TOOL_PATTERN = re.compile(
    r'^`([A-Za-z][A-Za-z0-9_.:-]*)`\*?$'
)
FOCUS_TERM_PATTERN = re.compile(r'[A-Za-z0-9_]{3,}')


def get_focus_terms(focus):
    """Return stable search terms from an optional generation focus."""
    if not focus:
        return []
    return list(dict.fromkeys(
        match.group(0).lower()
        for match in FOCUS_TERM_PATTERN.finditer(focus)
    ))


def score_focus_match(filename, summary, focus_terms):
    """Score a resource by filename and excerpt matches for the focus."""
    filename_lower = filename.lower()
    summary_lower = summary.lower()
    return sum(
        filename_lower.count(term) * 10 + summary_lower.count(term)
        for term in focus_terms
    )


def select_context_files(md_files, limit=20, file_summaries=None, focus=None):
    """Select representative resources across documented interfaces."""
    selected = []
    file_summaries = file_summaries or {}
    focus_terms = get_focus_terms(focus)

    if focus_terms:
        ranked_files = sorted(
            md_files,
            key=lambda filename: (
                -score_focus_match(
                    filename,
                    file_summaries.get(filename, ''),
                    focus_terms
                ),
                filename
            )
        )
        for filename in ranked_files:
            if score_focus_match(
                filename,
                file_summaries.get(filename, ''),
                focus_terms
            ) == 0:
                break
            selected.append(filename)
            if len(selected) == min(limit, 5):
                if len(selected) == limit:
                    return selected
                break

    for marker in CONTEXT_FILE_MARKERS:
        matches = sorted(filename for filename in md_files if marker in filename.lower())
        for filename in matches[:2]:
            if filename not in selected:
                selected.append(filename)
            if len(selected) == limit:
                return selected

    for filename in md_files:
        if filename not in selected:
            selected.append(filename)
        if len(selected) == limit:
            break

    return selected


def extract_mcp_capabilities(markdown):
    """Extract documented MCP tool names and descriptions from Markdown tables."""
    capabilities = {}

    for line in markdown.splitlines():
        cells = [cell.strip() for cell in line.strip().split('|')]
        if len(cells) < 2:
            continue

        tool_match = MCP_TABLE_TOOL_PATTERN.fullmatch(cells[0])
        if not tool_match:
            continue

        tool_name = tool_match.group(1)
        description = re.sub(r'\s+', ' ', cells[-1]).strip()
        capabilities[tool_name] = description

    return capabilities


def build_context_excerpt(content, focus=None):
    """Build a compact excerpt with headings and focus-matching passages."""
    parts = [content[:CONTEXT_PREFIX_CHARS].strip()]
    focus_terms = get_focus_terms(focus)
    focus_passages = []
    for term in focus_terms:
        for match in re.finditer(re.escape(term), content, re.IGNORECASE):
            start = max(0, match.start() - 180)
            end = min(len(content), match.end() + 420)
            passage = content[start:end].strip()
            if passage and passage not in focus_passages:
                focus_passages.append(passage)
            if len(focus_passages) == 3:
                break
        if len(focus_passages) == 3:
            break

    if focus_passages:
        parts.append('Focus matches:\n' + '\n...\n'.join(focus_passages))

    headings = re.findall(r'^#{1,3}\s+.+$', content, re.MULTILINE)
    if headings:
        parts.append('Headings:\n' + '\n'.join(headings[:30]))

    return '\n\n'.join(part for part in parts if part)[:CONTEXT_EXCERPT_CHARS]


def prepare_context_from_files(output_dir, focus=None):
    """Read scraped markdown files and prepare context for LLM"""
    md_files = []
    file_summaries = {}
    mcp_capabilities = {}

    # Get all .md files from resources subdirectory
    resources_dir = os.path.join(output_dir, 'resources')

    if not os.path.exists(resources_dir):
        return md_files, file_summaries, mcp_capabilities

    for filename in os.listdir(resources_dir):
        if filename.endswith('.md'):
            md_files.append(filename)

    # Sort for consistent ordering
    md_files.sort()

    # Build compact excerpts and inspect complete MCP resources for tool tables.
    for filename in md_files:
        filepath = os.path.join(resources_dir, filename)
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
                file_summaries[filename] = build_context_excerpt(content, focus)
                if 'mcp' in filename.lower():
                    mcp_capabilities.update(extract_mcp_capabilities(content))
        except Exception as e:
            print(f"Warning: Could not read {filename}: {e}")

    return md_files, file_summaries, mcp_capabilities


def validate_codex_skill_content(skill_content):
    """Return an error message when SKILL.md is not Codex-compatible."""
    frontmatter_match = re.match(r'\A---\s*\n(.*?)\n---\s*(?:\n|\Z)', skill_content, re.DOTALL)
    if not frontmatter_match:
        return 'SKILL.md must begin with YAML frontmatter delimited by --- lines.'

    frontmatter = frontmatter_match.group(1)
    name_match = re.search(r'^name:\s*["\']?([^"\'\s]+)["\']?\s*$', frontmatter, re.MULTILINE)
    if not name_match:
        return 'SKILL.md frontmatter must include a name.'

    name = name_match.group(1)
    if not name.startswith('use-'):
        return 'SKILL.md name must begin with use-.'
    if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', name) or len(name) > 64:
        return 'SKILL.md name must use lowercase letters, numbers, and hyphens, and be at most 64 characters.'

    description_match = re.search(r'^description:\s*(?:\||>|.+)$', frontmatter, re.MULTILINE)
    if not description_match:
        return 'SKILL.md frontmatter must include a description.'

    if description_match.group(0).rstrip().endswith(('|', '>')):
        description_lines = re.findall(r'^[ \t]+(.+)$', frontmatter[description_match.end():], re.MULTILINE)
        description = '\n'.join(description_lines)
    else:
        description = description_match.group(0).split(':', 1)[1].strip()
    if not description or len(description) > MAX_SKILL_DESCRIPTION_CHARS:
        return (
            'SKILL.md description must be between 1 and '
            f'{MAX_SKILL_DESCRIPTION_CHARS} characters.'
        )

    body = skill_content[frontmatter_match.end():].strip()
    if not body:
        return 'SKILL.md must include instructions after its frontmatter.'
    if 'resources/' not in body:
        return 'SKILL.md instructions must reference the resources/ directory.'

    return None


RESOURCE_REFERENCE_PATTERN = re.compile(
    r'(?<![A-Za-z0-9_/.-])((?:resources/)?[A-Za-z0-9_*?.-]+\.md)'
)
MCP_TOOL_PATTERN = re.compile(r'\bmcp\s+(?:server\s+)?tools?\b')
MCP_CURRENT_STATE_TERMS = ('current state', 'current workspace', 'live state', 'live workspace')
MCP_OPERATION_PATTERN = re.compile(
    r'\b(?:operation|operations|action|actions|create|update|write|execute)\b'
)
EXAMPLES_SECTION_PATTERN = re.compile(
    r'(?im)^(?:(?:#{1,6}\s+)examples?\b[^\n]*|examples?\b[^\n]*:)\s*$'
)


def extract_skill_description(skill_content):
    """Extract the description value from SKILL.md frontmatter."""
    frontmatter_match = re.match(
        r'\A---\s*\n(.*?)\n---\s*(?:\n|\Z)',
        skill_content,
        re.DOTALL
    )
    if not frontmatter_match:
        return ''

    frontmatter = frontmatter_match.group(1)
    description_match = re.search(r'^description:\s*(.*)$', frontmatter, re.MULTILINE)
    if not description_match:
        return ''

    value = description_match.group(1).strip()
    if value not in ('|', '>'):
        return value.strip('"\'')

    description_lines = []
    remaining_lines = frontmatter[description_match.end():].splitlines()
    for line in remaining_lines:
        if line.startswith((' ', '\t')):
            description_lines.append(line.strip())
        elif description_lines:
            break

    return '\n'.join(description_lines)


def validate_skill_description(skill_content):
    """Return an error when the discovery description is not concise."""
    description = extract_skill_description(skill_content)
    if not description:
        return 'SKILL.md frontmatter must include a description.'
    if len(description) > MAX_SKILL_DESCRIPTION_CHARS:
        return (
            'SKILL.md description must be at most '
            f'{MAX_SKILL_DESCRIPTION_CHARS} characters.'
        )
    return None


def extract_examples_section(skill_content):
    """Return the Markdown examples section when one is present."""
    section_match = EXAMPLES_SECTION_PATTERN.search(skill_content)
    if not section_match:
        return ''

    section_start = section_match.end()
    next_heading = re.search(
        r'^#{1,6}\s+.+$',
        skill_content[section_start:],
        re.MULTILINE
    )
    section_end = (
        section_start + next_heading.start()
        if next_heading
        else len(skill_content)
    )
    return skill_content[section_start:section_end]


def validate_mcp_examples(skill_content, mcp_capabilities):
    """Require MCP examples to cite at least one documented tool."""
    examples_section = extract_examples_section(skill_content)
    if not examples_section:
        return []

    example_blocks = re.split(
        r'(?m)(?=^\s*(?:[-*+]\s+|\d+[.)]\s+))',
        examples_section
    )
    example_blocks = [block.strip() for block in example_blocks if block.strip()]
    errors = []
    known_tools = set(mcp_capabilities)
    for example in example_blocks:
        if 'mcp' not in example.lower():
            continue
        if not any(
            re.search(
                rf'(?<![A-Za-z0-9_]){re.escape(tool)}(?![A-Za-z0-9_])',
                example
            )
            for tool in known_tools
        ):
            errors.append(
                'Every MCP example must name at least one exact tool from the '
                'documented MCP tool inventory.'
            )

    return list(dict.fromkeys(errors))


def score_mcp_capability_focus(tool_name, description, focus_terms):
    """Score an MCP capability by its lexical overlap with the focus."""
    tool_terms = re.findall(r'[a-z0-9]{3,}', tool_name.lower())
    description_terms = re.findall(r'[a-z0-9]{3,}', description.lower())

    def matches_focus(term):
        return any(
            term == focus_term
            or (
                min(len(term), len(focus_term)) >= 4
                and (term in focus_term or focus_term in term)
            )
            for focus_term in focus_terms
        )

    return (
        sum(10 for term in tool_terms if matches_focus(term))
        + sum(1 for term in description_terms if matches_focus(term))
    )


def select_mcp_example_tools(mcp_capabilities, focus=None, limit=8):
    """Select deterministic MCP examples, preferring focus-relevant tools."""
    tool_names = sorted(mcp_capabilities)
    focus_terms = get_focus_terms(focus)
    if not focus_terms:
        return tool_names[:limit]

    ranked_tools = sorted(
        tool_names,
        key=lambda tool_name: (
            -score_mcp_capability_focus(
                tool_name,
                mcp_capabilities[tool_name],
                focus_terms
            ),
            tool_name
        )
    )
    focused_tools = [
        tool_name
        for tool_name in ranked_tools
        if score_mcp_capability_focus(
            tool_name,
            mcp_capabilities[tool_name],
            focus_terms
        ) > 0
    ]
    return focused_tools[:limit] if focused_tools else tool_names[:limit]


def ensure_mcp_routing(skill_content, md_files, mcp_capabilities=None, focus=None):
    """Add deterministic MCP routing when the generated instructions omit it."""
    mcp_files = sorted(filename for filename in md_files if 'mcp' in filename.lower())
    if not mcp_files:
        return skill_content

    mcp_capabilities = mcp_capabilities or {}

    frontmatter_match = re.match(
        r'\A---\s*\n(.*?)\n---\s*(?:\n|\Z)',
        skill_content,
        re.DOTALL
    )
    body = skill_content[frontmatter_match.end():].lower() if frontmatter_match else ''
    mcp_path = f'resources/{mcp_files[0]}'
    has_complete_routing = (
        mcp_path.lower() in body
        and MCP_TOOL_PATTERN.search(body)
        and any(term in body for term in MCP_CURRENT_STATE_TERMS)
        and MCP_OPERATION_PATTERN.search(body)
        and (
            not mcp_capabilities
            or any(tool.lower() in body for tool in mcp_capabilities)
        )
    )
    if has_complete_routing:
        return skill_content

    documented_tools = ''
    if mcp_capabilities:
        example_tools = ', '.join(
            f'`{tool}`'
            for tool in select_mcp_example_tools(mcp_capabilities, focus)
        )
        documented_tools = (
            f' Documented examples include {example_tools}. '
            'Use only tools named in the MCP reference.'
        )

    routing_section = f'''## MCP documentation and live tools

Read `{mcp_path}` for documented MCP capabilities and setup. Treat documentation as static reference material. When available, use live MCP tools for current state and user-requested operations.{documented_tools}'''
    return f'{skill_content.rstrip()}\n\n{routing_section}\n'


def validate_skill_resource_references(skill_content, md_files):
    """Return errors for missing, shortened, or undiscoverable resource paths."""
    allowed_files = set(md_files)
    exact_resource_references = set()
    errors = []

    for match in RESOURCE_REFERENCE_PATTERN.finditer(skill_content):
        reference = match.group(1)

        if reference == 'SKILL.md':
            continue

        if not reference.startswith('resources/'):
            is_markdown_link_label = (
                match.start() > 0
                and skill_content[match.start() - 1] == '['
                and skill_content[match.end():].startswith('](resources/')
            )
            if not is_markdown_link_label:
                errors.append(
                    f"Markdown resource reference must use its full resources/ path: {reference}"
                )
            continue

        filename_pattern = reference.removeprefix('resources/')
        if '*' in filename_pattern or '?' in filename_pattern:
            if not any(fnmatch(filename, filename_pattern) for filename in allowed_files):
                errors.append(f"Resource pattern matches no files: {reference}")
            continue

        exact_resource_references.add(filename_pattern)
        if filename_pattern not in allowed_files:
            errors.append(f"Resource file does not exist: {reference}")

    if not exact_resource_references:
        errors.append('SKILL.md must name at least one exact resources/<filename>.md path.')

    mcp_files = sorted(filename for filename in md_files if 'mcp' in filename.lower())
    if mcp_files:
        frontmatter_match = re.match(
            r'\A---\s*\n(.*?)\n---\s*(?:\n|\Z)',
            skill_content,
            re.DOTALL
        )
        body = skill_content[frontmatter_match.end():].lower() if frontmatter_match else ''
        description = extract_skill_description(skill_content).lower()

        if 'mcp' not in description:
            errors.append('MCP documentation exists, so the SKILL.md description must include MCP.')
        if not any(filename in exact_resource_references for filename in mcp_files):
            allowed_mcp_paths = ', '.join(f'resources/{filename}' for filename in mcp_files)
            errors.append(
                f"SKILL.md must name an exact MCP resource path. Available: {allowed_mcp_paths}"
            )
        if not MCP_TOOL_PATTERN.search(body):
            errors.append(
                'MCP routing must identify available MCP tools as distinct from documentation.'
            )
        if not any(term in body for term in MCP_CURRENT_STATE_TERMS):
            errors.append(
                'MCP routing must say that available MCP tools provide current or live service state.'
            )
        if not MCP_OPERATION_PATTERN.search(body):
            errors.append(
                'MCP routing must cover user-requested operations or actions through available MCP tools.'
            )

    return list(dict.fromkeys(errors))


def parse_skill_generation_response(llm_response, extracted_name):
    """Parse an LLM response into the cleaned name and SKILL.md content."""
    cleaned_response = llm_response.strip()
    if cleaned_response.startswith('```'):
        first_newline = cleaned_response.find('\n')
        if first_newline != -1:
            cleaned_response = cleaned_response[first_newline + 1:]
        if cleaned_response.endswith('```'):
            cleaned_response = cleaned_response[:-3].rstrip()

    cleaned_response = cleaned_response.replace('\\\n', '')

    try:
        response_data = json.loads(cleaned_response)
    except json.JSONDecodeError as error:
        return extracted_name, llm_response, f'JSON parsing failed: {error}'

    cleaned_name = response_data.get('cleaned_name', extracted_name)
    skill_content = response_data.get('skill_content', '')
    if not skill_content:
        return cleaned_name, skill_content, 'skill_content is empty in the JSON response.'

    return cleaned_name, skill_content, None


def collect_skill_validation_errors(
    skill_type,
    skill_content,
    md_files,
    mcp_capabilities=None
):
    """Collect structural and resource-routing errors for a generated skill."""
    errors = []
    mcp_capabilities = mcp_capabilities or {}
    if skill_type == 'codex':
        codex_error = validate_codex_skill_content(skill_content)
        if codex_error:
            errors.append(codex_error)

    if skill_type != 'codex':
        description_error = validate_skill_description(skill_content)
        if description_error:
            errors.append(description_error)
    errors.extend(validate_skill_resource_references(skill_content, md_files))
    errors.extend(validate_mcp_examples(skill_content, mcp_capabilities))
    return list(dict.fromkeys(errors))


def build_skill_retry_message(
    user_message,
    llm_response,
    errors,
    md_files,
    mcp_capabilities=None
):
    """Add actionable validation feedback for one correction attempt."""
    error_list = '\n'.join(f'- {error}' for error in errors)
    mcp_capabilities = mcp_capabilities or {}
    mcp_files = sorted(filename for filename in md_files if 'mcp' in filename.lower())
    mcp_correction = ''
    if mcp_files:
        mcp_path = f'resources/{mcp_files[0]}'
        capability_correction = ''
        if mcp_capabilities:
            capability_correction = (
                '\nDocumented MCP tools: '
                + ', '.join(f'`{tool}`' for tool in sorted(mcp_capabilities))
                + '. Every MCP example must name at least one of these exact tools.'
            )
        mcp_correction = f'''

Include MCP in the frontmatter description. Use this routing guidance in SKILL.md:
"Read `{mcp_path}` for documented MCP capabilities and setup. Treat documentation as static reference material. When available, use live MCP tools for current state and user-requested operations."{capability_correction}'''

    return f"""{user_message}

Your previous response failed validation:
{error_list}

Previous response:
{llm_response}
{mcp_correction}

Return a corrected JSON response. Exact Markdown file references must use their complete resources/<filename>.md paths. Search patterns must begin with resources/ and match the supplied file list. Never use a bare Markdown filename or pattern."""


def generate_skill_md(
    extracted_name,
    source_url,
    output_dir,
    skill_type,
    show_deploy_instructions=False,
    focus=None
):
    """Generate a target-specific SKILL.md file using an LLM."""
    print("\n" + "="*60)
    print("Generating SKILL.md file...")
    print("="*60)

    # Load and validate configuration
    config = LLMConfig()
    try:
        config.validate()
    except ValueError as e:
        print(f"\n✗ Configuration error: {e}")
        print("\nSkipping SKILL.md generation. To enable:")
        print("1. Copy env.example to .env")
        print("2. Add your LLM API key and configuration")
        return output_dir  # Return original directory

    # Prepare context from scraped files
    md_files, file_summaries, mcp_capabilities = prepare_context_from_files(
        output_dir,
        focus
    )

    if not md_files:
        print("✗ No markdown files found to create skill from")
        return output_dir  # Return original directory

    print(f"Found {len(md_files)} documentation files")

    context_files = select_context_files(
        md_files,
        file_summaries=file_summaries,
        focus=focus
    )
    context_summaries = [
        f"- resources/{filename}: {file_summaries.get(filename, '')}"
        for filename in context_files
    ]
    focus_context = ''
    if focus:
        focus_context = f'''Generation focus: {focus}
Prioritize this focus in routing and examples when the documentation supports it.

'''
    mcp_context = ''
    if mcp_capabilities:
        mcp_context = '''Documented MCP tools:
{}

Every MCP example must name at least one exact tool from this inventory.

'''.format('\n'.join(
            f'- `{tool}`: {description}'
            for tool, description in sorted(mcp_capabilities.items())
        ))

    # Build user message for LLM
    user_message = f"""Extracted domain name from URL: {extracted_name}
Source URL: {source_url}

{focus_context}{mcp_context}Scraped documentation files ({len(md_files)} total) in resources/ subdirectory:
{chr(10).join(f"- resources/{f}" for f in md_files)}

Sample content from files:
{chr(10).join(context_summaries)}

Please clean the product name (if needed) and create a complete SKILL.md file.
Remember: All documentation files are in the resources/ subdirectory."""

    try:
        generation_message = user_message
        cleaned_name = extracted_name
        skill_content = ''

        for attempt in range(2):
            retry_label = " correction retry" if attempt else ""
            print(f"Calling {config.provider} ({config.model}){retry_label}...")
            llm_response = call_llm(
                config,
                SKILL_GENERATION_PROMPTS[skill_type],
                generation_message
            )
            cleaned_name, skill_content, parse_error = parse_skill_generation_response(
                llm_response,
                extracted_name
            )
            if not parse_error:
                skill_content = ensure_mcp_routing(
                    skill_content,
                    md_files,
                    mcp_capabilities,
                    focus
                )

            validation_errors = []
            if parse_error:
                validation_errors.append(parse_error)
            validation_errors.extend(
                collect_skill_validation_errors(
                    skill_type,
                    skill_content,
                    md_files,
                    mcp_capabilities
                )
            )

            if not validation_errors:
                break

            print("✗ Generated SKILL.md failed validation:")
            for validation_error in validation_errors:
                print(f"  - {validation_error}")

            if attempt == 1:
                print("✗ Correction retry failed. SKILL.md was not saved.")
                return output_dir

            generation_message = build_skill_retry_message(
                user_message,
                llm_response,
                validation_errors,
                md_files,
                mcp_capabilities
            )

        # Create final skill name with "use-" prefix
        final_skill_name = f"use-{cleaned_name}"

        # Check if we need to rename the folder
        current_dir_name = os.path.basename(os.path.abspath(output_dir))
        if final_skill_name != current_dir_name:
            # Calculate new directory path
            parent_dir = os.path.dirname(os.path.abspath(output_dir))
            new_output_dir = os.path.join(parent_dir, final_skill_name)

            if extracted_name != cleaned_name:
                print(f"\n🧹 Cleaned playful URL: {extracted_name} → {cleaned_name}")
            print(f"📝 Final skill name: {final_skill_name}")
            print(f"   Renaming folder: {current_dir_name} → {final_skill_name}")

            # Rename the directory
            os.rename(output_dir, new_output_dir)
            output_dir = new_output_dir
        else:
            print(f"\n📝 Skill name: {final_skill_name}")

        # Save SKILL.md
        skill_path = os.path.join(output_dir, 'SKILL.md')
        with open(skill_path, 'w', encoding='utf-8') as f:
            f.write(skill_content)

        print(f"✓ Generated: SKILL.md")
        print(f"\n{'='*60}")
        print(f"✅ Skill created successfully!")
        print(f"{'='*60}")
        print(f"\nLocation: {os.path.abspath(output_dir)}")
        if show_deploy_instructions:
            if skill_type == 'claude':
                print(f"\nDeploy to Claude platforms:")
                print(f"  • Claude Code:      cp -r {output_dir} ~/.claude/skills/")
                print(f"  • Claude.ai/Desktop: ZIP and upload via Settings > Features")
                print(f"  • Agent SDK:        cp -r {output_dir} <project>/.claude/skills/")
                print(f"  • Claude API:       Upload via /v1/skills endpoint")
            else:
                print(f"\nDeploy to Codex:")
                print(f"  • Personal skill:   cp -r {output_dir} ~/.agents/skills/")
            print(f"\nSee README.md 'Deploying Generated Skills' section for full instructions")
        return output_dir  # Return potentially renamed directory

    except Exception as e:
        print(f"✗ Failed to generate SKILL.md: {e}")
        import traceback
        traceback.print_exc()
        return output_dir  # Return original directory


def main():
    parser = argparse.ArgumentParser(
        description='Scrape HTML content and convert to Markdown from all sub-URLs'
    )
    parser.add_argument(
        '--url',
        required=True,
        action='append',
        dest='urls',
        help='A starting URL to scrape. Repeat this option to combine multiple documentation sections.'
    )
    parser.add_argument(
        '--type',
        required=True,
        choices=('claude', 'codex'),
        help='The skill format to generate'
    )
    parser.add_argument(
        '-o', '--output',
        default=None,
        help='Output directory for the generated skill (default: the selected target personal skills directory)'
    )
    parser.add_argument(
        '--all-domains',
        action='store_true',
        help='Scrape URLs from all domains (default: same domain only)'
    )
    parser.add_argument(
        '--include-path',
        action='append',
        default=[],
        help='Only scrape URL paths with this prefix. Repeat this option to allow multiple sections.'
    )
    parser.add_argument(
        '--focus',
        default=None,
        help='Prioritize a documented use case in generated routing and examples.'
    )

    args = parser.parse_args()

    # Load credentials only for an actual run, never while importing this module.
    load_dotenv()

    custom_output = args.output is not None

    # Set output inside the selected target's personal skills directory if not specified.
    # This directory will be renamed later to "use-{cleaned_name}" by the LLM.
    if args.output is None:
        extracted_name = get_domain_name(args.urls[0])
        print(f"Extracted domain name: {extracted_name}")
        args.output = get_default_output_dir(args.type, extracted_name)

    # Create output directory
    os.makedirs(args.output, exist_ok=True)

    links = set()
    for source_url in args.urls:
        print(f"Fetching links from: {source_url}")
        source_links = get_all_links(source_url)
        print(f"Found {len(source_links)} links from this starting URL")
        links.add(normalize_url(source_url))
        links.update(source_links)

    if not links:
        print("No links found!")
        return

    # Filter by domain (default behavior, unless --all-domains is specified)
    if not args.all_domains:
        base_domains = {urlparse(source_url).netloc for source_url in args.urls}
        links = {link for link in links if urlparse(link).netloc in base_domains}
        print(f"Filtering to starting domains only: {', '.join(sorted(base_domains))}")

    if args.include_path:
        include_paths = tuple(
            path if path.startswith('/') else f'/{path}'
            for path in args.include_path
        )
        links = {
            link for link in links
            if urlparse(link).path.startswith(include_paths)
        }
        print(f"Filtering to path prefixes: {', '.join(include_paths)}")

    print(f"\nFound {len(links)} links to scrape")
    print(f"Saving to: {args.output}/\n")

    # Scrape all links with progress bar
    successful = 0
    for link in tqdm(links, desc="Scraping pages", unit="page"):
        if scrape_url(link, args.output):
            successful += 1

    print(f"\n{'='*60}")
    print(f"Scraped {successful}/{len(links)} pages successfully")
    print(f"Files saved to: {os.path.abspath(args.output)}")

    # Group and merge files based on URL path depth
    if successful > 0:
        group_and_merge_files(args.output)
        postprocess_resource_files(args.output)

    # Generate SKILL.md file
    if successful > 0:
        # Extract domain name for LLM to clean
        extracted_name = get_domain_name(args.urls[0])
        source_description = '\n'.join(args.urls)
        final_output_dir = generate_skill_md(
            extracted_name,
            source_description,
            args.output,
            args.type,
            show_deploy_instructions=custom_output,
            focus=args.focus
        )
        # Update args.output in case the directory was renamed
        args.output = final_output_dir


if __name__ == '__main__':
    main()

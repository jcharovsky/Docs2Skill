#!/usr/bin/env python3
"""
Markdown Scraper - Scrapes HTML content and converts to Markdown from all sub-URLs
"""

import argparse
import os
import sys
import re
import subprocess
from urllib.parse import urljoin, urlparse

# Auto-install dependencies if missing
def install_requirements():
    """Install required packages if not already installed"""
    required_packages = {
        'requests': 'requests',
        'bs4': 'beautifulsoup4',
        'html2text': 'html2text',
        'dotenv': 'python-dotenv',
        'tqdm': 'tqdm'
    }

    missing_packages = []
    for import_name, package_name in required_packages.items():
        try:
            __import__(import_name)
        except ImportError:
            missing_packages.append(package_name)

    if missing_packages:
        print(f"Installing missing dependencies: {', '.join(missing_packages)}")
        subprocess.check_call([sys.executable, '-m', 'pip', 'install'] + missing_packages)
        print("Dependencies installed successfully!\n")

# Install requirements before importing
install_requirements()

import requests
from bs4 import BeautifulSoup
import html2text
from dotenv import load_dotenv
import json
from tqdm import tqdm


# Load environment variables
load_dotenv()


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
SKILL_GENERATION_PROMPT = """You are an expert at creating Claude Code Skills based on documentation.

Your task is to create a SKILL.md file that enables Claude to effectively use the provided documentation to help users.

## SKILL.md Structure Requirements:

1. **YAML Frontmatter** (required and optional fields):
```yaml
---
name: skill-name-here
description: |
  Brief description of what this skill does and when Claude should use it.
  Must be specific and include trigger terms. Max 1024 characters.
version: 1.0.0
dependencies: python>=3.8, package>=1.0.0
---
```

Note: `version` and `dependencies` are optional but recommended:
- **version**: Use semantic versioning (e.g., "1.0.0") or date-based (e.g., "2025-01-24")
- **dependencies**: Only include if the documentation describes code that requires specific packages. For pure documentation skills, this can be omitted.

2. **Name Requirements**:
   - Lowercase only
   - Max 64 characters
   - Use hyphens for spaces (e.g., "use-phantombuster")
   - Should reflect the domain/service
   - **CRITICAL**: Cannot contain reserved words: "anthropic" or "claude"
   - **CRITICAL**: Cannot contain XML tags

3. **Description Requirements** (CRITICAL):
   - Maximum 1024 characters
   - Write in third person (e.g., "Processes files" not "I can help you")
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
   - For any resource file over 100 lines, include a table of contents at the top
   - Use progressive disclosure: keep SKILL.md as overview, detailed content goes in resources/
   - **IMPORTANT**: Keep file references one level deep - all files should link directly from SKILL.md, not from other resource files
   - **IMPORTANT**: Avoid time-sensitive information (no dates, version cutoffs). Use "Old patterns" sections for deprecated approaches instead
   - **IMPORTANT**: When multiple approaches exist, provide a clear default recommendation rather than listing many equivalent options
   - **IMPORTANT**: Use consistent terminology throughout - choose one term and stick with it (e.g., always "API endpoint", never mix with "URL" or "route")

5. **Examples Section**:
   - Provide 2-3 example interactions
   - Show what kinds of questions users might ask
   - Demonstrate how Claude should respond

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
   - Has proper YAML frontmatter with:
     * `name: use-{cleaned_name}` (e.g., "use-phantombuster", "use-n8n")
     * `description` in third person with specific trigger terms
     * `version` field (use "1.0.0" for new skills)
     * `dependencies` field (optional - only include if the documentation describes specific package requirements)
   - Provides clear instructions for Claude on how to use the documentation in resources/
   - Includes relevant examples
   - Uses forward slashes for all file paths (e.g., resources/guide.md)
   - Follows all best practices above

Output ONLY valid JSON with these two fields, nothing else."""


def call_llm(config, user_message):
    """Call LLM API based on provider"""
    if config.provider == 'anthropic':
        return call_anthropic(config, user_message)
    elif config.provider == 'gemini':
        return call_gemini(config, user_message)
    elif config.provider in ['openai', 'openrouter', 'grok', 'ollama']:
        return call_openai_compatible(config, user_message)
    else:
        raise ValueError(f"Unsupported provider: {config.provider}")


def call_anthropic(config, user_message):
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
        'system': SKILL_GENERATION_PROMPT,
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


def call_openai_compatible(config, user_message):
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
                'content': SKILL_GENERATION_PROMPT
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


def call_gemini(config, user_message):
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
                        'text': f"{SKILL_GENERATION_PROMPT}\n\n{user_message}"
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


def get_all_links(url):
    """Extract all links from a webpage"""
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')

        links = set()
        for link in soup.find_all('a', href=True):
            absolute_url = urljoin(url, link['href'])
            links.add(absolute_url)

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


def convert_html_to_markdown(html_content):
    """Convert HTML content to Markdown format"""
    # Parse HTML
    soup = BeautifulSoup(html_content, 'html.parser')

    # Remove unwanted elements
    for element in soup(['script', 'style', 'nav', 'footer', 'header', 'iframe', 'noscript']):
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
    markdown = h.handle(cleaned_html)

    return markdown.strip()


def scrape_url(url, output_dir):
    """Scrape HTML content and convert to Markdown"""
    try:
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


def prepare_context_from_files(output_dir):
    """Read scraped markdown files and prepare context for LLM"""
    md_files = []
    file_summaries = []

    # Get all .md files from resources subdirectory
    resources_dir = os.path.join(output_dir, 'resources')

    if not os.path.exists(resources_dir):
        return md_files, file_summaries

    for filename in os.listdir(resources_dir):
        if filename.endswith('.md'):
            md_files.append(filename)

    # Sort for consistent ordering
    md_files.sort()

    # Read first few lines of each file to get a sense of content
    for filename in md_files:
        filepath = os.path.join(resources_dir, filename)
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                # Read first 500 characters to get a summary
                content = f.read(500)
                file_summaries.append(f"- resources/{filename}: {content[:200]}...")
        except Exception as e:
            print(f"Warning: Could not read {filename}: {e}")

    return md_files, file_summaries


def generate_skill_md(extracted_name, source_url, output_dir):
    """Generate SKILL.md file using LLM and clean playful URL names"""
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
    md_files, file_summaries = prepare_context_from_files(output_dir)

    if not md_files:
        print("✗ No markdown files found to create skill from")
        return output_dir  # Return original directory

    print(f"Found {len(md_files)} documentation files")

    # Build user message for LLM
    user_message = f"""Extracted domain name from URL: {extracted_name}
Source URL: {source_url}

Scraped documentation files ({len(md_files)} total) in resources/ subdirectory:
{chr(10).join(f"- resources/{f}" for f in md_files)}

Sample content from files:
{chr(10).join(file_summaries[:10])}

Please clean the product name (if needed) and create a complete SKILL.md file.
Remember: All documentation files are in the resources/ subdirectory."""

    # Call LLM
    try:
        print(f"Calling {config.provider} ({config.model})...")
        llm_response = call_llm(config, user_message)

        # Parse JSON response
        try:
            response_data = json.loads(llm_response)
            cleaned_name = response_data.get('cleaned_name', extracted_name)
            skill_content = response_data.get('skill_content', '')
        except json.JSONDecodeError:
            print("Warning: LLM did not return valid JSON. Using extracted name as-is.")
            cleaned_name = extracted_name
            skill_content = llm_response

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
        print(f"\nDeploy to Claude platforms:")
        print(f"  • Claude Code:      cp -r {output_dir} ~/.claude/skills/")
        print(f"  • Claude.ai/Desktop: ZIP and upload via Settings > Features")
        print(f"  • Agent SDK:        cp -r {output_dir} <project>/.claude/skills/")
        print(f"  • Claude API:       Upload via /v1/skills endpoint")
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
    parser.add_argument('url', help='The URL to scrape content from')
    parser.add_argument(
        '-o', '--output',
        default=None,
        help='Output directory for markdown files (default: ../{domain})'
    )
    parser.add_argument(
        '--all-domains',
        action='store_true',
        help='Scrape URLs from all domains (default: same domain only)'
    )

    args = parser.parse_args()

    # Set output directory to ../{extracted_name} (parent directory) if not specified
    # This will be renamed later to "use-{cleaned_name}" by the LLM
    if args.output is None:
        extracted_name = get_domain_name(args.url)
        print(f"Extracted domain name: {extracted_name}")
        args.output = os.path.join('..', extracted_name)

    # Create output directory
    os.makedirs(args.output, exist_ok=True)

    print(f"Fetching links from: {args.url}")
    links = get_all_links(args.url)

    if not links:
        print("No links found!")
        return

    # Filter by domain (default behavior, unless --all-domains is specified)
    if not args.all_domains:
        base_domain = urlparse(args.url).netloc
        links = {link for link in links if urlparse(link).netloc == base_domain}
        print(f"Filtering to same domain only: {base_domain}")

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

    # Generate SKILL.md file
    if successful > 0:
        # Extract domain name for LLM to clean
        extracted_name = get_domain_name(args.url)
        final_output_dir = generate_skill_md(extracted_name, args.url, args.output)
        # Update args.output in case the directory was renamed
        args.output = final_output_dir


if __name__ == '__main__':
    main()
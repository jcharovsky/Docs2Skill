import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from docs2skill import (
    add_contents_section,
    convert_html_to_markdown,
    generate_skill_md,
    get_all_links,
    normalize_url,
    postprocess_resource_files,
    remove_markdown_chrome,
    select_context_files,
    validate_skill_resource_references,
)


class Docs2SkillTests(unittest.TestCase):
    def test_normalize_url_removes_fragments(self):
        self.assertEqual(
            normalize_url('https://example.com/docs/page?tab=web#setup'),
            'https://example.com/docs/page?tab=web'
        )

    @patch('docs2skill.requests.get')
    def test_get_all_links_deduplicates_fragments(self, mock_get):
        response = Mock()
        response.content = b'''
            <a href="/docs/page#one">One</a>
            <a href="/docs/page#two">Two</a>
        '''
        response.raise_for_status.return_value = None
        mock_get.return_value = response

        links = get_all_links('https://example.com/docs/')

        self.assertEqual(links, {'https://example.com/docs/page'})

    def test_convert_html_to_markdown_removes_documentation_chrome(self):
        markdown = convert_html_to_markdown(b'''
            <html><body>
              <a class="skip-main">Skip to content</a>
              <div id="nav_bar">Documentation menu</div>
              <div class="copy-for-llm-page-header">Copy for LLM</div>
              <a id="cc_prompt">New Stuff!</a>
              <article><h1>Useful content</h1><p>Keep this.</p></article>
            </body></html>
        ''')

        self.assertIn('Useful content', markdown)
        self.assertIn('Keep this.', markdown)
        self.assertNotIn('Skip to content', markdown)
        self.assertNotIn('Documentation menu', markdown)
        self.assertNotIn('Copy for LLM', markdown)
        self.assertNotIn('New Stuff!', markdown)

    def test_remove_markdown_chrome_cleans_legacy_resources(self):
        markdown = '''Skip to content

![](/docs/assets/img/sidebar-rail-collapse.svg) Press Arrow down to open the documentation menu without expanding the sidebar.

Press `Esc` to close the menu

# Keep this heading

Keep this paragraph.

__ Back to top
'''

        cleaned = remove_markdown_chrome(markdown)

        self.assertIn('# Keep this heading', cleaned)
        self.assertIn('Keep this paragraph.', cleaned)
        self.assertNotIn('Skip to content', cleaned)
        self.assertNotIn('sidebar-rail-collapse.svg', cleaned)
        self.assertNotIn('Press `Esc`', cleaned)
        self.assertNotIn('Back to top', cleaned)

    def test_postprocess_deduplicates_fragments_and_adds_contents(self):
        repeated_body = '\n'.join(f'Line {index}' for index in range(120))
        content = f'''# Example

## Page

**Source:** https://example.com/docs/page#one

{repeated_body}

---

## Page

**Source:** https://example.com/docs/page#two

{repeated_body}
'''

        with tempfile.TemporaryDirectory() as temporary_directory:
            resources = Path(temporary_directory) / 'resources'
            resources.mkdir()
            resource = resources / 'example.md'
            resource.write_text(content)

            stats = postprocess_resource_files(temporary_directory)
            repaired = resource.read_text()
            second_stats = postprocess_resource_files(temporary_directory)

        self.assertEqual(stats['duplicates_removed'], 1)
        self.assertEqual(stats['contents_added'], 1)
        self.assertEqual(repaired.count('**Source:**'), 1)
        self.assertIn('## Contents', repaired)
        self.assertNotIn('#one', repaired)
        self.assertNotIn('#two', repaired)
        self.assertEqual(second_stats['files_updated'], 0)

    def test_postprocess_deduplicates_identical_content_from_query_urls(self):
        repeated_body = '\n'.join(f'Line {index}' for index in range(120))
        content = f'''# Example

## First tab

**Source:** https://example.com/docs/page?tab=first

{repeated_body}

---

## Second tab

**Source:** https://example.com/docs/page?tab=second

{repeated_body}
'''

        with tempfile.TemporaryDirectory() as temporary_directory:
            resources = Path(temporary_directory) / 'resources'
            resources.mkdir()
            resource = resources / 'example.md'
            resource.write_text(content)

            stats = postprocess_resource_files(temporary_directory)
            repaired = resource.read_text()

        self.assertEqual(stats['duplicates_removed'], 1)
        self.assertEqual(repaired.count('**Source:**'), 1)
        self.assertIn('?tab=first', repaired)
        self.assertNotIn('?tab=second', repaired)

    def test_add_contents_uses_level_one_heading_fallback(self):
        body = '\n'.join(f'Endpoint {index}' for index in range(120))
        content = f'''# api-home

**Source URL:** https://example.com/docs/api/home/

---

# API Guide

{body}
'''

        updated = add_contents_section(content)

        self.assertIn('## Contents', updated)
        self.assertIn('- API Guide', updated)

    def test_select_context_files_includes_each_interface(self):
        files = sorted([
            *(f'docs-api-section-{index}.md' for index in range(25)),
            'docs-developer_guide-mcp_server.md',
            'docs-developer_guide-sdk_integration.md',
            'docs-developer_guide-cli.md',
            'docs-compliance_documentation.md',
            'docs-user_guide-messaging.md',
        ])

        selected = select_context_files(files, limit=10)

        self.assertIn('docs-developer_guide-mcp_server.md', selected)
        self.assertIn('docs-developer_guide-sdk_integration.md', selected)
        self.assertIn('docs-developer_guide-cli.md', selected)
        self.assertIn('docs-compliance_documentation.md', selected)
        self.assertIn('docs-user_guide-messaging.md', selected)

    def test_resource_validation_rejects_shortened_mcp_filename(self):
        skill_content = '''---
name: use-example
description: Example MCP documentation.
---

Read mcp_server.md for current workspace state and requested operations.
'''

        errors = validate_skill_resource_references(
            skill_content,
            ['docs-developer_guide-mcp_server.md']
        )

        self.assertTrue(any('full resources/ path' in error for error in errors))
        self.assertTrue(any('exact MCP resource path' in error for error in errors))
        self.assertTrue(any('available MCP tools' in error for error in errors))

    def test_resource_validation_allows_matching_full_path_patterns(self):
        skill_content = '''---
name: use-example
description: Example API documentation.
---

Search resources/docs-api-*.md, then read resources/docs-api-home.md.
'''

        errors = validate_skill_resource_references(
            skill_content,
            ['docs-api-home.md']
        )

        self.assertEqual(errors, [])

    def test_resource_validation_rejects_nonmatching_full_path_patterns(self):
        skill_content = '''---
name: use-example
description: Example API documentation.
---

Search resources/docs-sdk-*.md, then read resources/docs-api-home.md.
'''

        errors = validate_skill_resource_references(
            skill_content,
            ['docs-api-home.md']
        )

        self.assertTrue(any('matches no files' in error for error in errors))

    def test_generate_skill_retries_invalid_resource_references(self):
        invalid_skill = '''---
name: use-braze
description: Braze MCP documentation.
---

Read mcp_server.md for current workspace state and requested operations.
'''
        valid_skill = '''---
name: use-braze
description: Braze MCP documentation for API and workspace operations.
---

Read [the MCP reference](resources/docs-developer_guide-mcp_server.md) for behavior. Use available MCP tools for current workspace state and user-requested operations.
'''
        responses = [
            json.dumps({'cleaned_name': 'braze', 'skill_content': invalid_skill}),
            json.dumps({'cleaned_name': 'braze', 'skill_content': valid_skill}),
        ]
        config = Mock(provider='openai', model='test-model')
        config.validate.return_value = True

        with tempfile.TemporaryDirectory() as temporary_directory:
            output_directory = Path(temporary_directory) / 'braze'
            resources = output_directory / 'resources'
            resources.mkdir(parents=True)
            (resources / 'docs-developer_guide-mcp_server.md').write_text(
                '# MCP\n\nCurrent workspace state and operations.'
            )

            with patch('docs2skill.LLMConfig', return_value=config), patch(
                'docs2skill.call_llm',
                side_effect=responses
            ) as mock_call_llm:
                result = generate_skill_md(
                    'braze',
                    'https://example.com/docs',
                    str(output_directory),
                    'codex'
                )

            generated_skill = Path(result) / 'SKILL.md'
            retry_message = mock_call_llm.call_args_list[1].args[2]

            self.assertEqual(mock_call_llm.call_count, 2)
            self.assertTrue(generated_skill.exists())
            self.assertEqual(generated_skill.read_text(), valid_skill)
            self.assertIn('failed validation', retry_message)
            self.assertIn('resources/docs-developer_guide-mcp_server.md', retry_message)
            self.assertIn('Treat documentation as static reference material.', retry_message)
            self.assertIn('use live MCP tools for current state', retry_message)
            self.assertIn('user-requested operations', retry_message)

    def test_generate_skill_completes_mcp_routing_before_validation(self):
        incomplete_skill = '''---
name: use-braze
description: Braze API and MCP documentation.
---

Search resources/docs-api-*.md and read resources/docs-developer_guide-mcp_server.md for MCP setup.
'''
        response = json.dumps({
            'cleaned_name': 'braze',
            'skill_content': incomplete_skill,
        })
        config = Mock(provider='openai', model='test-model')
        config.validate.return_value = True

        with tempfile.TemporaryDirectory() as temporary_directory:
            output_directory = Path(temporary_directory) / 'braze'
            resources = output_directory / 'resources'
            resources.mkdir(parents=True)
            (resources / 'docs-api-home.md').write_text('# API')
            (resources / 'docs-developer_guide-mcp_server.md').write_text('# MCP')

            with patch('docs2skill.LLMConfig', return_value=config), patch(
                'docs2skill.call_llm',
                side_effect=[response, response]
            ) as mock_call_llm:
                result = generate_skill_md(
                    'braze',
                    'https://example.com/docs',
                    str(output_directory),
                    'codex'
                )

            generated_skill = Path(result) / 'SKILL.md'
            generated_content = generated_skill.read_text()

            self.assertEqual(mock_call_llm.call_count, 1)
            self.assertIn('Treat documentation as static reference material.', generated_content)
            self.assertIn('use live MCP tools for current state', generated_content)
            self.assertIn('user-requested operations', generated_content)

    def test_generate_skill_stops_after_failed_correction(self):
        invalid_skill = '''---
name: use-braze
description: Braze documentation.
---

Read mcp_server.md.
'''
        invalid_response = json.dumps({
            'cleaned_name': 'braze',
            'skill_content': invalid_skill,
        })
        config = Mock(provider='openai', model='test-model')
        config.validate.return_value = True

        with tempfile.TemporaryDirectory() as temporary_directory:
            output_directory = Path(temporary_directory) / 'braze'
            resources = output_directory / 'resources'
            resources.mkdir(parents=True)
            (resources / 'docs-developer_guide-mcp_server.md').write_text('# MCP')

            with patch('docs2skill.LLMConfig', return_value=config), patch(
                'docs2skill.call_llm',
                side_effect=[invalid_response, invalid_response]
            ) as mock_call_llm:
                result = generate_skill_md(
                    'braze',
                    'https://example.com/docs',
                    str(output_directory),
                    'codex'
                )

            self.assertEqual(mock_call_llm.call_count, 2)
            self.assertEqual(result, str(output_directory))
            self.assertFalse((output_directory / 'SKILL.md').exists())


if __name__ == '__main__':
    unittest.main()

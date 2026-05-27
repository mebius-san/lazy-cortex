"""
PyCharm offline inspection runner.

Run PyCharm code inspections from the command line via inspect.sh,
parse the XML output, and report findings in a terminal-friendly format.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
# noinspection PyPep8Naming
# stdlib convention
import xml.etree.ElementTree as ET
# noinspection PyCompatibility
import tomllib

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# hardcoded exclusions that should never be scanned
HARDCODED_EXCLUDES = [ '.venv', '__pycache__' ]

# candidate paths for PyCharm inspect.sh (searched in order)
INSPECT_SH_CANDIDATES = [
  os.path.expanduser('~/Applications/PyCharm.app/Contents/bin/inspect.sh'),
  '/Applications/PyCharm.app/Contents/bin/inspect.sh',
  os.path.expanduser('~/Applications/PyCharm Professional.app/Contents/bin/inspect.sh'),
  '/Applications/PyCharm Professional.app/Contents/bin/inspect.sh',
]

# system path entries that must NOT be symlinked (locked by the running IDE instance)
SYSTEM_SKIP = { '.pid', '.port', '.appinfo', 'index', 'caches' }

# config path entries that must NOT be symlinked (lock file held by the running IDE instance)
CONFIG_SKIP = { '.lock' }

# prefix used by PyCharm in XML output file paths
PROJECT_DIR_PREFIX = 'file://$PROJECT_DIR$/'

# map PyCharm severity levels to standard linter levels (mypy/pcf style)
SEVERITY_MAP = {
  'error': 'error',
  'warning': 'warning',
  'weak warning': 'note',
  'info': 'note',
  'typo': 'note',
  'grammar': 'note',
  'server problem': 'error',
}


# ----------------------------------------------------------------------------------------
def load_config() -> dict:
  """
  Load configuration from pyproject.toml.

  Returns:
    Configuration dictionary for the pch tool.
  """
  config_path = 'pyproject.toml'
  if not os.path.exists(config_path):
    return {}

  with open(config_path, 'rb') as fle:
    data = tomllib.load(fle)

  return data.get('tool', {}).get('pch', {})


# ----------------------------------------------------------------------------------------
def find_inspect_sh() -> str | None:
  """
  Locate the PyCharm inspect.sh command-line tool.

  Search the PYCHARM_HOME environment variable first, then known installation paths.

  Returns:
    Absolute path to inspect.sh, or None if not found.
  """
  # check PYCHARM_HOME environment variable first
  pycharm_home = os.environ.get('PYCHARM_HOME')
  if pycharm_home:
    candidate = os.path.join(pycharm_home, 'bin', 'inspect.sh')
    if os.path.isfile(candidate):
      return candidate

  # check known installation paths
  for candidate in INSPECT_SH_CANDIDATES:
    if os.path.isfile(candidate):
      return candidate

  return None


# ----------------------------------------------------------------------------------------
def find_system_path() -> str | None:
  """
  Locate the active PyCharm system (caches) directory.

  Returns:
    Absolute path to the system directory, or None if not found.
  """
  caches_base = os.path.expanduser('~/Library/Caches/JetBrains')
  # guard: no JetBrains caches directory
  if not os.path.isdir(caches_base):
    return None

  # find PyCharm directories, pick the newest by version
  candidates = sorted(
      (d for d in os.listdir(caches_base) if d.startswith('PyCharm')),
      reverse = True
  )
  for name in candidates:
    path = os.path.join(caches_base, name)
    if os.path.isdir(path):
      return path

  return None


# ----------------------------------------------------------------------------------------
def find_config_path() -> str | None:
  """
  Locate the active PyCharm configuration directory.

  Returns:
    Absolute path to the config directory, or None if not found.
  """
  config_base = os.path.expanduser('~/Library/Application Support/JetBrains')
  # guard: no JetBrains config directory
  if not os.path.isdir(config_base):
    return None

  # find PyCharm directories, pick the newest by version
  candidates = sorted(
      (d for d in os.listdir(config_base) if d.startswith('PyCharm')),
      reverse = True
  )
  for name in candidates:
    path = os.path.join(config_base, name)
    if os.path.isdir(path):
      return path

  return None


# ----------------------------------------------------------------------------------------
def prepare_sandbox_config(sandbox_dir: str, real_config: str | None) -> str:
  """
  Create a sandbox config directory with symlinks to the real PyCharm config.

  Symlink everything except the lock file so the inspection gets SDK and
  interpreter settings while avoiding lock conflicts with the running IDE.

  Args:
    sandbox_dir: root sandbox directory.
    real_config: path to the real PyCharm config directory, or None.

  Returns:
    Path to the sandbox config directory.
  """
  config_dir = os.path.join(sandbox_dir, 'config')
  os.makedirs(config_dir)

  # guard: no real config to symlink from
  if real_config is None or not os.path.isdir(real_config):
    return config_dir

  for entry in os.listdir(real_config):
    # guard: skip lock file
    if entry in CONFIG_SKIP:
      continue
    src = os.path.join(real_config, entry)
    dst = os.path.join(config_dir, entry)
    os.symlink(src, dst)

  return config_dir


# ----------------------------------------------------------------------------------------
def prepare_sandbox_system(sandbox_dir: str, real_system: str | None) -> str:
  """
  Create a sandbox system directory with symlinks to the real PyCharm system.

  Symlink everything except exclusively-locked entries (.pid, index, caches)
  so the inspection gets Python stubs and SDK data while avoiding lock conflicts.

  Args:
    sandbox_dir: root sandbox directory.
    real_system: path to the real PyCharm system directory, or None.

  Returns:
    Path to the sandbox system directory.
  """
  system_dir = os.path.join(sandbox_dir, 'system')
  os.makedirs(system_dir)

  # guard: no real system to symlink from
  if real_system is None or not os.path.isdir(real_system):
    return system_dir

  for entry in os.listdir(real_system):
    # guard: skip exclusively-locked entries
    if entry in SYSTEM_SKIP:
      continue
    src = os.path.join(real_system, entry)
    dst = os.path.join(system_dir, entry)
    os.symlink(src, dst)

  return system_dir


# ----------------------------------------------------------------------------------------
def run_inspection(
    inspect_sh: str,
    project_dir: str,
    profile_path: str,
    output_dir: str,
    module_path: str,
    sandbox_dir: str
) -> int:
  """
  Invoke PyCharm inspect.sh on the project.

  Use a sandboxed JVM config so inspections can run while the IDE is open.

  Args:
    inspect_sh: absolute path to inspect.sh.
    project_dir: absolute path to the project root.
    profile_path: absolute path to the inspection profile XML.
    output_dir: directory where XML results will be written.
    module_path: subdirectory to limit inspection scope (or '.' for full project).
    sandbox_dir: temporary directory for JVM config, system, and log paths.

  Returns:
    The subprocess return code.
  """
  cmd = [ inspect_sh, project_dir, profile_path, output_dir, '-v0' ]

  # always pass -d to limit scope to the target directory;
  # without -d, inspect.sh inspects ALL registered modules (including sibling repos)
  cmd.extend([ '-d', os.path.join(project_dir, module_path) ])

  # write a VM options file that redirects system/config/log to the sandbox
  # so inspect.sh can run alongside an open PyCharm IDE;
  # the sandbox config directory symlinks real SDK and interpreter settings
  # but omits the lock file to avoid DirectoryLock conflicts
  vm_opts_path = os.path.join(sandbox_dir, 'pch.vmoptions')
  with open(vm_opts_path, 'w', encoding = 'utf-8') as fle:
    fle.write(f'-Didea.system.path={sandbox_dir}/system\n')
    fle.write(f'-Didea.config.path={sandbox_dir}/config\n')
    fle.write(f'-Didea.log.path={sandbox_dir}/log\n')

  env = os.environ.copy()
  env['PYCHARM_VM_OPTIONS'] = vm_opts_path

  result = subprocess.run(cmd, capture_output = True, text = True, check = False, env = env)

  # check whether the output directory has any XML results
  has_results = any(f.endswith('.xml') for f in os.listdir(output_dir)) if os.path.isdir(output_dir) else False

  # exit code 1 with results means "issues found" — that is normal operation;
  # non-zero without results means inspect.sh itself failed;
  # only surface stderr/stdout on fatal failures (PyCharm dumps noisy JVM warnings on every run)
  # guard: only treat as fatal when no output was produced
  if result.returncode != 0 and not has_results:
    if result.stdout:
      print(result.stdout.rstrip())
    if result.stderr:
      print(result.stderr.rstrip(), file = sys.stderr)
    return result.returncode

  return 0


# ----------------------------------------------------------------------------------------
def parse_results(output_dir: str) -> list[tuple[str, int, str, str, str]]:
  """
  Parse PyCharm XML inspection output into structured findings.

  Args:
    output_dir: directory containing XML result files.

  Returns:
    List of tuples: (filepath, line, severity, inspection_name, description).
  """
  problems: list[tuple[str, int, str, str, str]] = []

  # guard: skip if output directory has no files
  if not os.path.isdir(output_dir):
    return problems

  for filename in sorted(os.listdir(output_dir)):
    # guard: skip non-XML files
    if not filename.endswith('.xml'):
      continue

    filepath = os.path.join(output_dir, filename)
    try:
      tree = ET.parse(filepath)
    except ET.ParseError as exc:
      print(f'pch: warning: failed to parse {filename}: {exc}', file = sys.stderr)
      continue

    root = tree.getroot()
    for problem in root.iter('problem'):
      file_elem = problem.find('file')
      line_elem = problem.find('line')
      problem_class_elem = problem.find('problem_class')
      description_elem = problem.find('description')

      # guard: skip malformed entries
      if file_elem is None or file_elem.text is None:
        continue
      # guard: skip entries without description
      if description_elem is None or description_elem.text is None:
        continue

      # strip the $PROJECT_DIR$ prefix from the file path
      raw_path = file_elem.text
      if raw_path.startswith(PROJECT_DIR_PREFIX):
        raw_path = raw_path[len(PROJECT_DIR_PREFIX):]

      line = int(line_elem.text) if line_elem is not None and line_elem.text else 0

      severity = ''
      inspection_name = ''
      if problem_class_elem is not None:
        severity = problem_class_elem.get('severity', '').lower()
        inspection_name = problem_class_elem.text or ''

      description = description_elem.text

      problems.append((raw_path, line, severity, inspection_name, description))

  return problems


# ----------------------------------------------------------------------------------------
def filter_results(
    problems: list[tuple[str, int, str, str, str]],
    module_path: str,
    exclude_substrings: list[str],
    include_extensions: list[str],
    ignore_inspections: list[str]
) -> list[tuple[str, int, str, str, str]]:
  """
  Filter inspection results by module path, exclusion list, and ignored inspections.

  Args:
    problems: list of parsed problem tuples.
    module_path: module path prefix to keep (or '.' for all).
    exclude_substrings: substrings to exclude from file paths.
    include_extensions: file extensions to include (e.g. '.py'); empty means all.
    ignore_inspections: inspection names to suppress from output.

  Returns:
    Filtered list of problem tuples.
  """
  filtered = []
  for item in problems:
    filepath = item[0]
    inspection_name = item[3]

    # apply module path filter (skip when scanning everything)
    # guard: only filter by prefix when a specific module is targeted
    if module_path != '.' and not filepath.startswith(module_path):
      continue

    # apply exclusion filter
    # guard: skip files matching any exclusion substring
    if any(sub in filepath for sub in exclude_substrings):
      continue

    # guard: skip files not matching any included extension
    if include_extensions and not any(filepath.endswith(ext) for ext in include_extensions):
      continue

    # guard: skip ignored inspections
    if inspection_name in ignore_inspections:
      continue

    filtered.append(item)

  return filtered


# ----------------------------------------------------------------------------------------
def format_problem(filepath: str, line: int, severity: str, inspection: str, description: str) -> str:
  """
  Format a single inspection finding for terminal output.

  Args:
    filepath: relative path to the source file.
    line: line number of the finding.
    severity: severity level (e.g. 'note', 'warning', 'error').
    inspection: inspection name.
    description: description of the finding.

  Returns:
    Formatted string matching mypy/pcf style: file:line: severity: description  [code].
  """
  level = SEVERITY_MAP.get(severity, severity or 'note')
  return f'{filepath}:{line}: {level}: {description}  [{inspection}]'


# ----------------------------------------------------------------------------------------
def main() -> None:
  """
  Entry point for the PyCharm inspection runner CLI tool.

  Parse arguments, run PyCharm inspections, and report findings.
  """
  # load configuration from pyproject.toml
  config = load_config()

  # setup CLI parser
  parser = argparse.ArgumentParser(description = 'Run PyCharm offline inspections')
  parser.add_argument('path', nargs = '?', default = '.',
                      help = 'target directory to inspect')
  parser.add_argument('--exclude', action = 'append', metavar = 'SUBSTRING',
                      help = 'exclude files or directories containing this substring')
  args = parser.parse_args()

  # normalize module path: strip leading ./ so it matches XML output paths
  module_path = args.path.removeprefix('./')

  # locate inspect.sh
  inspect_sh = find_inspect_sh()
  if inspect_sh is None:
    print('pch: PyCharm inspect.sh not found. Set PYCHARM_HOME or install PyCharm.', file = sys.stderr)
    sys.exit(1)

  # resolve project directory (cli/chk cd's to project root before invoking)
  project_dir = os.path.abspath('.')

  # resolve inspection profile
  profile_path = os.path.join(project_dir, '.idea', 'inspectionProfiles', 'Project_Default.xml')
  if not os.path.isfile(profile_path):
    print('pch: warning: inspection profile not found, using PyCharm defaults', file = sys.stderr)
    profile_path = ''

  # get excludes from config, CLI args can extend the list
  config_excludes = list(config.get('exclude', []))

  # when a specific path is targeted, drop config exclusions that match the target
  # so that explicitly requested directories (e.g. tests/) are not silently skipped
  if module_path != '.':
    target_parts = module_path.rstrip('/').split('/')
    config_excludes = [ e for e in config_excludes
                        if e not in target_parts ]

  exclude_substrings = HARDCODED_EXCLUDES + config_excludes
  if args.exclude:
    exclude_substrings.extend(args.exclude)

  # get file extensions to include from config (empty = all)
  include_extensions = list(config.get('include_extensions', []))

  # get inspection names to ignore from config
  ignore_inspections = list(config.get('ignore', []))

  # prepare sandbox: symlink real config (SDK settings) and system (stubs) minus locked entries
  real_config = find_config_path()
  real_system = find_system_path()
  sandbox_dir = tempfile.mkdtemp(prefix = 'pch_')
  prepare_sandbox_config(sandbox_dir, real_config)
  prepare_sandbox_system(sandbox_dir, real_system)
  output_dir = os.path.join(sandbox_dir, 'out')
  os.makedirs(output_dir)
  try:
    print(f'pch: running PyCharm inspections on \'{module_path}\' (this may take a while)...')

    ret = run_inspection(inspect_sh, project_dir, profile_path, output_dir, module_path, sandbox_dir)
    # guard: non-zero here means inspect.sh failed without producing results
    if ret != 0:
      print('pch: inspect.sh failed', file = sys.stderr)
      sys.exit(1)

    # parse and filter results
    problems = parse_results(output_dir)
    problems = filter_results(problems, module_path, exclude_substrings, include_extensions, ignore_inspections)

  finally:
    shutil.rmtree(sandbox_dir, ignore_errors = True)

  # print findings grouped by file
  for filepath, line, severity, inspection, description in problems:
    print(format_problem(filepath, line, severity, inspection, description))

  # print summary (same style as pcf)
  if problems:
    file_count = len({ p[0] for p in problems })
    print(f'Found issues in {file_count} source files')
  else:
    print('Success: no issues found')


# run main if this is the top-level script
if __name__ == '__main__':
  main()

---
description: Test structure, naming, assertions, coverage, and test patterns for Python projects that adopt these conventions.
---
# Testing Guidelines

Test structure, naming, assertions, coverage, and test patterns
for Python projects that adopt these conventions.


## Test Directory Structure and file naming
- Mirror the source code structure in the test directory, examples:
  - `src/core/entity/entity.py` → `tests/core/entity/entity.py`
  - `src/meta/groups/base.py` → `tests/meta/groups/base.py`
- Do not create special test files to make other tests discoverable.
- Do not name test files other than files named in the original source code you are making tests for.
- Do not add any extra files to the test directory that are not directly testing a specific source code file.
- Do not combine tests for different source code files into a single test file.
- Do not add test methods or classes to the files inside the test root folders like `tests/test_*` — those files exist only to combine tests for different source code files into a single test file.
- Use `tests/<module_name>` folders to put test files for a specific module.

## Test Class Inheritance
- Inherit test classes from the project's base test class (referred to below as `<YourBaseTest>`) — the project-specific base test class appropriate for the class under test. When a project ships specialized base test classes for a given category (entities, data sets, etc.), use those.

## Test Class Naming
- Name test classes after the production class they test:
  - Example: `TestService`, `TestStore`, `TestRunContext`.
- If you need an auxiliary subclass of a production class for testing another class, name it with numeric suffixes:
  - Example: `Service1`, `Service2`, etc.

## Test Method Naming

### General Rules
- Always start with `test_`.
- Do **not** repeat the production class name — it is already present in the test class.
- Keep names under 35 characters.
- Use double underscores `__` only to separate feature from variation.
- Use docstrings for detail, not long method names.

### Conventions

### Allowed Patterns
- Initialization: `test_init__...`,`test_init`.
- Properties: `test_prop__...`.
- Magic methods: `test_add`, `test_sub`, `test_bool`.
- Functional grouping: `test_feature__case`, `test_feature`.

### Variation Rule
- Use __variation only if multiple cases exist.
```python
def test_isect__ok(self): ...
def test_isect__fail(self): ...
```

### Examples
- Correct:
```python
class TestMatrix(<YourBaseTest>):
  def test_init__def(self): ...
  def test_add(self): ...
  def test_prop__is_valid(self): ...
  def test_spawn__no_proto(self): ...
```
- Wrong (repeating class name in method):
```python
class TestMatrix(<YourBaseTest>):
  def test_matrix_init_with_defaults(self): ...
  def test_matrix_addition(self): ...
  def test_matrix_property_is_valid_yes(self): ...
  def test_matrix_string_representation(self): ...
  def test_matrix_spawn_no_proto(self): ...
  def test_spawn__proto_not_found(self): ...
```
- Wrong (using __variation without variations):
```python
def test_init__defaults__case1(self): ...
```

## Numeric & Geometry Tests
- Always use **floats** (not ints) in math/geometry tests unless specifically testing integer behavior.

## Logging in Tests
- Do **not** wrap test code in `with with_log_level(LogLevel.DEBUG):`.
- If warnings or errors are expected, use: `with with_log_level(LogLevel.CRITICAL):` block to suppress the logs, see the Logging Suppression in Tests Pattern section below.

## Test Method Docstrings
- Every test method should have a short descriptive docstring like production code.
- Docstrings should state what behavior is validated, not just restate the method name.

## Assert Statements
- **Assert statements are only allowed in unit tests.** Never use `assert` in production code — use explicit checks (e.g., `if`/`raise`, guard clauses, or type narrowing) instead.
- All assert statements **must** include descriptive messages:
```python
assert isinstance(transform, Matrix), f"expected Matrix instance, got {type(transform)}"
assert np.array_equal(transform.matrix, expected_matrix), f"expected matrix {expected_matrix}, got {transform.matrix}"
assert transform.n_dim == 2, f"expected n_dim=2, got {transform.n_dim}"
```
- Include both expected and actual values in assertion messages when appropriate.
- Use f-strings for dynamic assertion messages.
- The message should clearly indicate what the expected behavior is.
- **Use implicit booleanness for empty sequence/collection checks** (see Conditional Statements in `coding_guidelines.md`). Never write `== []`, `== {}`, or `== ()` — use `not x` / `x` instead:
  - Correct: `assert not items, f"expected [], got {items}"`
  - Correct: `assert items, f"expected non-empty list, got {items}"`
  - Wrong: `assert items == [], ...` (triggers pylint C1803: use-implicit-booleaness-not-comparison)
  - Wrong: `assert items == {}, ...`
  - Wrong: `assert items == (), ...`

## Test Organization
- Group related tests in the same test class.
- Use fixtures for a common test setup.
- Test error conditions and edge cases with `pytest.raises`:
```python
with pytest.raises(ValueError, match = "Matrix must be square"):
  Matrix(matrix = invalid_matrix)
```

## Test Coverage
- Aim for comprehensive test coverage.
- Test integration between different components.

## Sampling and Randomness Testing Notes
- When testing randomness (e.g., `DataRoll.reroll()`):
  - Assert value ranges (e.g., uniform samples in [0.0, 1.0]).
  - Prefer probabilistic change assertions (value changed with very high probability) rather than strict equality.
  - Avoid global RNG seeding unless the test explicitly requires a deterministic behavior.
- When testing operator overloading with unsupported types, rely on Python's standard `TypeError` generated via `NotImplemented` protocol. Example:
```python
with pytest.raises(TypeError, match = "unsupported operand type.*@.*DataRoll.*str"):
  roll @ "invalid"
```

## Test class docstrings
- Every test class should have a docstring describing what is being tested in that class.
- Always start the summary line with `Test unit for ` word.
- Omit any specific section, keep the Summary line only and make it short and simple.

## Test method docstrings
- Every test method should have a short descriptive docstring like production code.
- Docstrings should state what behavior is validated, not just restate the method name.
- Always start the summary line with `Test that ` phrase.
- Omit any specific section, keep the Summary line only and make it short and simple.

## Image Generation in Tests
- Tests that generate images MUST always add them to the project's base test class image buffer (commonly `<YourBaseTest>.images`).
- Use `self.images.append(image, name)` to add generated images to the buffer. Where:
  - `image` is the generated image object.
  - `name` is the name of the test method without the `test_` prefix and with the possible suffix indicating the variation (e.g., `__1`).
- This ensures that generated images are properly collected and can be saved for debugging or visual inspection.
- Never discard generated images without adding them to the buffer first.




# Test Patterns

## Logging Suppression in Tests Pattern
```python
with with_log_level(LogLevel.CRITICAL):
  # code that is expected to log warnings or errors
```

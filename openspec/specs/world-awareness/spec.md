## ADDED Requirements

### Requirement: Resource discovery awareness
系统 SHALL track resource discoveries and search observations as part of Minecraft world awareness.

#### Scenario: Record discovered resource
- **WHEN** Bot finds a supported resource block during search
- **THEN** 系统 SHALL record the resource type, block name, position, strategy, and discovery time in runtime memory

#### Scenario: Record depleted resource
- **WHEN** Bot mines or revisits a previously discovered resource block and the block is gone
- **THEN** 系统 SHALL mark that resource point as depleted

#### Scenario: Record search failure
- **WHEN** a resource search fails due to no resource, blocked path, timeout, or unsafe area
- **THEN** 系统 SHALL record enough context for future search attempts to avoid repeating the same failing choice

#### Scenario: Include search observations in status
- **WHEN** debug status or locator diagnostics are requested
- **THEN** 系统 SHALL be able to report recent resource discoveries, depleted points, and failure summaries for the current bot run

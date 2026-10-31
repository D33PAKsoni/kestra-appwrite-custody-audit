# Docker verification plan

This machine has no Docker Desktop or WSL installation. Docker verification is prepared for a Linux GitHub-hosted runner without changing Windows features or the original Appwrite project.

The `Docker blueprint verification` workflow installs Node 24, Python 3.12 and Java 25 on an Ubuntu 24.04 runner, runs the local suite, then starts checksum-verified Kestra 2.0.7 with Python plugin 1.18.4. Each script task runs in Docker with the blueprint's Python 3.12 image. Only the test namespace, explicit Docker host networking and fictional endpoint/credentials are overridden; Python task bodies are preserved.

Four scenarios exercise clean records, a historical missing sample later received, inconsistent custody and incomplete export. Expected failure gates must preserve their reports. JSON/CSV artifacts and `reports/docker-ci.json` are uploaded for inspection. The job does not receive real Appwrite keys, passwords or records.

The workflow is prepared but has not run. Its eventual result demonstrates Docker orchestration against a fictional transport. The separate live Appwrite verification is documented in `reports/LIVE_VERIFICATION.md`; do not describe the two evidence sets as a combined Docker-to-Appwrite run.

Source: [Kestra Docker task runner](https://kestra.io/plugins/core/docker-task-runner/io.kestra.plugin.scripts.runner.docker.docker). Host networking is used only so test containers can reach the runner's loopback fixture service. The contribution's normal configuration retains its default Docker networking and HTTPS Appwrite endpoint.

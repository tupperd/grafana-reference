Airgap bundle (Option B)
========================
This folder represents the "airgapped" media. After running prepare-bundle.sh
(from the parent directory, with network), it will contain:

  - grafana-enterprise.tar   (Docker image saved for transfer)
  - license.jwt              (Grafana Enterprise license)
  - plugins/                 (optional: unpacked plugin dirs, e.g. grafana-jira-datasource/)

To simulate airgap: disconnect Wi‑Fi or block outbound traffic, then from
the parent directory run: ./run-airgapped.sh

# Third-Party Notices

LanLens itself is licensed under the MIT License. Dependencies keep their own
licenses, and those terms matter when distributing source archives, packaged
builds or Docker images.

## Direct Dependency License Matrix

### Backend

| Dependency | Reported license | Use in LanLens | Notes |
|---|---|---|---|
| FastAPI | MIT | API framework | Permissive |
| Uvicorn | BSD-3-Clause | ASGI server | Permissive |
| SQLAlchemy | MIT | Database ORM | Permissive |
| python-jose | MIT | JWT handling | Permissive |
| bcrypt | Apache-2.0 | Password hashing | Permissive |
| python-nmap | GPL-3.0 | Per-device port scanning wrapper | Copyleft; preserve license notices and source availability when redistributing bundled builds |
| scapy | GPL-2.0-only | ARP scanning, DHCP monitor and passive discovery packet parsing | Copyleft; preserve license notices and source availability when redistributing bundled builds |
| manuf | Apache-2.0 or GPL-3.0 | MAC vendor lookup data | Use under Apache-2.0 terms for LanLens distribution |
| httpx | BSD-3-Clause | HTTP client | Permissive |
| APScheduler | MIT | Background jobs | Permissive |
| python-multipart | Apache-2.0 | Multipart form parsing | Permissive |
| netifaces | MIT | Network interface discovery | Permissive |
| websockets | BSD-3-Clause | WebSocket support | Permissive |
| Pydantic | MIT | Data validation | Permissive |
| pydantic-settings | MIT | Settings management | Permissive |
| Paramiko | LGPL-2.1 | SSH-related connectivity support | Weak copyleft; preserve notices and allow replacement/modification of the library when distributing bundled forms |
| pywinrm | MIT | Windows remote management | Permissive |

### Frontend

The direct frontend runtime dependencies are permissively licensed:

| Dependency | Reported license |
|---|---|
| axios | MIT |
| date-fns | MIT |
| React | MIT |
| React DOM | MIT |
| react-hot-toast | MIT |
| react-router-dom | MIT |
| Zustand | MIT |

The direct frontend development dependencies are permissively licensed:

| Dependency | Reported license |
|---|---|
| @playwright/test | Apache-2.0 |
| @types/react | MIT |
| @types/react-dom | MIT |
| @vitejs/plugin-react | MIT |
| autoprefixer | MIT |
| postcss | MIT |
| tailwindcss | MIT |
| TypeScript | Apache-2.0 |
| Vite | MIT |

## Redistribution Checklist

- Keep the LanLens MIT license text with source and binary distributions.
- Keep third-party package metadata and license files in packaged builds and
  container images.
- For GPL/LGPL dependencies bundled into images or installers, provide the
  corresponding dependency source or a clear written source offer according to
  the relevant license terms.
- Do not replace this notice with a blanket "all dependencies are permissive"
  statement; LanLens intentionally includes GPL/LGPL dependencies for network
  discovery features.
- Re-check this file whenever adding, replacing or upgrading dependencies.

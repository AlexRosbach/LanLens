# Applications dashboard

Enable Advanced View and Applications in Settings → Features → Inventory and CMDB, then save. Open Applications from the sidebar. The dashboard reads the latest successful installed_software finding per active, non-ignored device, including agent and Deep Scan data, independently of i-doit. A subsequent unrelated scan does not erase software observations. Products are grouped by observed name and publisher, with version and architecture shown per installation. Names are not guessed or merged using fuzzy matching. Search by application, version, publisher or device. Select an application to see installations and follow device links. Results and installation details are paginated. Existing inventory is reused; no new scan is required unless no software was collected. Observations are snapshots, not a guarantee of current installation status. Access requires authentication and the enabled feature. No i-doit credentials are used.

## Filters

Use the independent server/device/IP, application, publisher, version, architecture, device class and source filters together with global search. All filters are evaluated against the same installation before aggregation and pagination. Installation details and counters reflect the applied filters. Reset filters to restore the full inventory.

## Grouping

Switch between Application and Server / device grouping. Select a group to see installations or products on the exact device. Filters and pagination apply before grouping; all three counters reflect the filtered inventory.

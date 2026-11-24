using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Management;
using System.Net.Http;
using System.Diagnostics;
using System.ServiceProcess;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;
using Microsoft.Win32;

public class LanLensAgent : ServiceBase
{
    private const string ConfigPath = @"C:\ProgramData\LanLensAgent\agent.json";
    private Timer _timer;
    private int _reporting;
    private volatile bool _stopping;
    private readonly JavaScriptSerializer _json = new JavaScriptSerializer { MaxJsonLength = 16 * 1024 * 1024 };
    public LanLensAgent() { ServiceName = "LanLensAgent"; CanStop = true; AutoLog = true; }
    public static void Main() { ServiceBase.Run(new LanLensAgent()); }
    protected override void OnStart(string[] args) {
        _stopping = false;
        _timer = new Timer(Report, null, TimeSpan.Zero, Timeout.InfiniteTimeSpan);
    }
    protected override void OnStop() { _stopping = true; if (_timer != null) _timer.Dispose(); }

    private void Report(object state)
    {
        if (_stopping || Interlocked.Exchange(ref _reporting, 1) != 0) return;
        var interval = 60;
        try
        {
            var cfg = _json.Deserialize<Dictionary<string, object>>(File.ReadAllText(ConfigPath));
            interval = Math.Max(5, Math.Min(1440, Convert.ToInt32(cfg["interval_minutes"])));
            var adapter = new ManagementObjectSearcher("SELECT * FROM Win32_NetworkAdapterConfiguration WHERE IPEnabled = True").Get().Cast<ManagementObject>().FirstOrDefault(x => x["MACAddress"] != null);
            if (adapter == null) return;
            var os = new ManagementObjectSearcher("SELECT * FROM Win32_OperatingSystem").Get().Cast<ManagementObject>().FirstOrDefault();
            var ips = ((string[])adapter["IPAddress"] ?? new string[0]).Where(ip => !ip.Contains(":")).ToArray();
            cfg["sequence"] = Convert.ToInt64(cfg["sequence"]) + 1;
            // Persist before sending: a lost acknowledgement must not cause replay after restart.
            var temp = ConfigPath + ".tmp";
            File.WriteAllText(temp, _json.Serialize(cfg));
            File.Replace(temp, ConfigPath, null);
            var payload = new Dictionary<string, object> {
                { "sequence", cfg["sequence"] }, { "hostname", Environment.MachineName }, { "primary_mac", adapter["MACAddress"].ToString() },
                { "os_info", os == null ? "Windows" : String.Format("{0} {1}", os["Caption"], os["Version"]) },
                { "kernel_version", os == null ? "" : Convert.ToString(os["BuildNumber"]) }, { "ip_addresses", ips }, { "software", InstalledSoftware() },
                { "findings", AgentFindings() }, { "platform", "windows" }
            };
            using (var client = new HttpClient())
            {
                client.Timeout = TimeSpan.FromSeconds(30);
                client.DefaultRequestHeaders.Authorization = new System.Net.Http.Headers.AuthenticationHeaderValue("Bearer", Convert.ToString(cfg["agent_id"]) + "." + Convert.ToString(cfg["agent_secret"]));
                var response = client.PostAsync(Convert.ToString(cfg["server_url"]).TrimEnd('/') + "/api/agents/report", new StringContent(_json.Serialize(payload), Encoding.UTF8, "application/json")).Result;
                if (!response.IsSuccessStatusCode) EventLog.WriteEntry("LanLensAgent", "Inventory report rejected: " + (int)response.StatusCode, EventLogEntryType.Warning);
            }
        }
        catch (Exception) { EventLog.WriteEntry("LanLensAgent", "Inventory collection or reporting failed.", EventLogEntryType.Warning); }
        finally {
            Interlocked.Exchange(ref _reporting, 0);
            if (!_stopping) {
                try { _timer.Change(TimeSpan.FromMinutes(interval), Timeout.InfiniteTimeSpan); }
                catch (ObjectDisposedException) { }
            }
        }
    }

    private static List<Dictionary<string, string>> InstalledSoftware()
    {
        var result = new List<Dictionary<string, string>>();
        foreach (var root in new[] { Registry.LocalMachine.OpenSubKey(@"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"), Registry.LocalMachine.OpenSubKey(@"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall") })
        {
            if (root == null) continue;
            foreach (var name in root.GetSubKeyNames()) using (var app = root.OpenSubKey(name))
            {
                var display = app == null ? null : app.GetValue("DisplayName") as string;
                if (String.IsNullOrWhiteSpace(display)) continue;
                result.Add(new Dictionary<string, string> { { "name", display }, { "version", Convert.ToString(app.GetValue("DisplayVersion")) }, { "publisher", Convert.ToString(app.GetValue("Publisher")) } });
                if (result.Count >= 2000) return result;
            }
        }
        return result;
    }

    // Use the same read-only local PowerShell collectors as WinRM Deep Scan.
    // Failures (for example an absent IIS or Hyper-V module) are omitted rather
    // than making the agent report fail.
    private List<Dictionary<string, object>> AgentFindings()
    {
        var commands = new[] {
            new [] { "hardware", "computer_system", "Get-CimInstance Win32_ComputerSystem | ConvertTo-Json -Compress" },
            new [] { "hardware", "bios", "Get-CimInstance Win32_BIOS | ConvertTo-Json -Compress" },
            new [] { "hardware", "processor", "Get-CimInstance Win32_Processor | Select Name,NumberOfCores,MaxClockSpeed | ConvertTo-Json -Compress" },
            new [] { "hardware", "physical_memory", "Get-CimInstance Win32_PhysicalMemory | Select Capacity,Speed | ConvertTo-Json -Compress" },
            new [] { "hardware", "disk_drives", "Get-CimInstance Win32_DiskDrive | Select Model,Size,MediaType | ConvertTo-Json -Compress" },
            new [] { "service", "running_services", "Get-Service | ? {$_.Status -eq 'Running'} | Select Name,DisplayName,Status | ConvertTo-Json -Compress" },
            new [] { "audit", "windows_features", "if(Get-Command Get-WindowsFeature -EA SilentlyContinue){Get-WindowsFeature|?{$_.InstallState -eq 'Installed'}|Select Name,DisplayName|ConvertTo-Json -Compress}" },
            new [] { "audit", "licensing", "Get-CimInstance SoftwareLicensingProduct|?{$_.PartialProductKey -and $_.Name -like 'Windows*'}|Select Name,LicenseStatus|ConvertTo-Json -Compress" },
            new [] { "audit", "iis_sites", "if(Get-Module -ListAvailable WebAdministration){Import-Module WebAdministration;Get-Website|Select Name,State,PhysicalPath|ConvertTo-Json -Compress}" },
            new [] { "audit", "hyper_v_vms", "if(Get-Command Get-VM -EA SilentlyContinue){Get-VM|Select Name,State,Generation|ConvertTo-Json -Compress}" },
            new [] { "audit", "sql_instances", "Get-Service|?{$_.Name -like 'MSSQL*'}|Select Name,DisplayName,Status|ConvertTo-Json -Compress" },
            new [] { "audit", "ad_domain", "if(Get-Command Get-ADDomain -EA SilentlyContinue){(Get-ADDomain).DNSRoot|ConvertTo-Json -Compress}" },
            new [] { "audit", "dhcp_scopes", "if(Get-Command Get-DhcpServerv4Scope -EA SilentlyContinue){Get-DhcpServerv4Scope|Select ScopeId,Name,State|ConvertTo-Json -Compress}" },
        };
        var result = new List<Dictionary<string, object>>();
        foreach (var command in commands)
        {
            var value = PowerShellJson(command[2]);
            if (value != null) result.Add(new Dictionary<string, object> {
                { "finding_type", command[0] }, { "key", command[1] }, { "value", value }, { "source", "lanlens_windows_agent" }
            });
        }
        return result;
    }

    private object PowerShellJson(string command)
    {
        try {
            var psi = new ProcessStartInfo("powershell.exe", "-NoProfile -NonInteractive -ExecutionPolicy Bypass -Command \"" + command.Replace("\"", "\\\"") + "\"") {
                CreateNoWindow = true, UseShellExecute = false, RedirectStandardOutput = true
            };
            using (var process = Process.Start(psi)) {
                var output = new StringBuilder();
                process.OutputDataReceived += (sender, args) => {
                    if (args.Data != null && output.Length < 128000) output.AppendLine(args.Data);
                };
                process.BeginOutputReadLine();
                if (!process.WaitForExit(30000)) {
                    try { process.Kill(); } catch (InvalidOperationException) { }
                    return null;
                }
                process.WaitForExit();
                var json = output.ToString().Trim();
                return process.ExitCode != 0 || String.IsNullOrWhiteSpace(json) || json.Length > 128000 ? null : _json.DeserializeObject(json);
            }
        } catch { return null; }
    }
}

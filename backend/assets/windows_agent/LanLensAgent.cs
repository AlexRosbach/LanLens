using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Management;
using System.Net.Http;
using System.ServiceProcess;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;
using Microsoft.Win32;

public class LanLensAgent : ServiceBase
{
    private const string ConfigPath = @"C:\ProgramData\LanLensAgent\agent.json";
    private Timer _timer;
    private readonly JavaScriptSerializer _json = new JavaScriptSerializer { MaxJsonLength = 16 * 1024 * 1024 };
    public LanLensAgent() { ServiceName = "LanLensAgent"; CanStop = true; AutoLog = true; }
    public static void Main() { ServiceBase.Run(new LanLensAgent()); }
    protected override void OnStart(string[] args) { Report(null); }
    protected override void OnStop() { if (_timer != null) _timer.Dispose(); }

    private void Report(object state)
    {
        try
        {
            var cfg = _json.Deserialize<Dictionary<string, object>>(File.ReadAllText(ConfigPath));
            var interval = Convert.ToInt32(cfg["interval_minutes"]);
            if (_timer == null) _timer = new Timer(Report, null, TimeSpan.FromMinutes(interval), TimeSpan.FromMinutes(interval));
            var adapter = new ManagementObjectSearcher("SELECT * FROM Win32_NetworkAdapterConfiguration WHERE IPEnabled = True").Get().Cast<ManagementObject>().FirstOrDefault(x => x["MACAddress"] != null);
            if (adapter == null) return;
            var os = new ManagementObjectSearcher("SELECT * FROM Win32_OperatingSystem").Get().Cast<ManagementObject>().FirstOrDefault();
            var ips = ((string[])adapter["IPAddress"] ?? new string[0]).Where(ip => !ip.Contains(":")).ToArray();
            cfg["sequence"] = Convert.ToInt32(cfg["sequence"]) + 1;
            var payload = new Dictionary<string, object> {
                { "sequence", cfg["sequence"] }, { "hostname", Environment.MachineName }, { "primary_mac", adapter["MACAddress"].ToString() },
                { "os_info", os == null ? "Windows" : String.Format("{0} {1}", os["Caption"], os["Version"]) },
                { "kernel_version", os == null ? "" : Convert.ToString(os["BuildNumber"]) }, { "ip_addresses", ips }, { "software", InstalledSoftware() }
            };
            using (var client = new HttpClient())
            {
                client.Timeout = TimeSpan.FromSeconds(30);
                client.DefaultRequestHeaders.Authorization = new System.Net.Http.Headers.AuthenticationHeaderValue("Bearer", Convert.ToString(cfg["agent_id"]) + "." + Convert.ToString(cfg["agent_secret"]));
                var response = client.PostAsync(Convert.ToString(cfg["server_url"]).TrimEnd('/') + "/api/agents/report", new StringContent(_json.Serialize(payload), Encoding.UTF8, "application/json")).Result;
                if (response.IsSuccessStatusCode) File.WriteAllText(ConfigPath, _json.Serialize(cfg));
            }
        }
        catch (Exception ex) { EventLog.WriteEntry("LanLensAgent", ex.Message, EventLogEntryType.Warning); }
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
}

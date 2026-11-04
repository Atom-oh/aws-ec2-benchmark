// ASP.NET Core Minimal API on Kestrel — web framework benchmark. Server GC + TieredPGO are the
// ASP.NET Core production defaults (set explicitly in Web.csproj). Endpoint spec shared with docker/web-*/.
using System.Runtime.InteropServices;
using System.Security.Cryptography;

var builder = WebApplication.CreateSlimBuilder(args);
builder.Logging.ClearProviders();
builder.WebHost.UseUrls("http://0.0.0.0:8080");
var app = builder.Build();

var seed = "benchmark-seed"u8.ToArray();
const int Rounds = 2000;
var version = $"dotnet {RuntimeInformation.FrameworkDescription} aspnetcore kestrel {RuntimeInformation.ProcessArchitecture}";

app.MapGet("/plaintext", () => Results.Text("Hello, World!", "text/plain"));
app.MapGet("/json", () => Results.Json(new Message("Hello, World!"), AppJson.Default.Message));
app.MapGet("/compute", () =>
{
    byte[] h = seed;
    for (int i = 0; i < Rounds; i++) h = SHA256.HashData(h);
    return Results.Text(Convert.ToHexStringLower(h), "text/plain");
});
app.MapGet("/health", () => Results.Text("ok", "text/plain"));
app.MapGet("/version", () => Results.Text(version, "text/plain"));
app.Run();

public record Message(string message);

[System.Text.Json.Serialization.JsonSerializable(typeof(Message))]
public partial class AppJson : System.Text.Json.Serialization.JsonSerializerContext { }

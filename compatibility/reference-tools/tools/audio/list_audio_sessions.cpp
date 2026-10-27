// Read-only Windows playback-session inventory for loopback attribution.
#include <windows.h>
#include <mmdeviceapi.h>
#include <audiopolicy.h>
#include <endpointvolume.h>
#include <wrl/client.h>
#include <cstdio>
#include <cwchar>
#include <chrono>
#include <thread>
#include <cmath>
using Microsoft::WRL::ComPtr;
int wmain(int argc, wchar_t** argv) {
    double seconds = 0;
    DWORD targetPid = 0;
    for (int i = 1; i < argc; ++i) {
        if (!std::wcscmp(argv[i], L"--seconds") && i + 1 < argc) {
            wchar_t* end = nullptr;
            seconds = std::wcstod(argv[++i], &end);
            if (end == argv[i] || *end || !std::isfinite(seconds) || seconds < 0 || seconds > 3600) return 2;
        } else if (!std::wcscmp(argv[i], L"--target-pid") && i + 1 < argc) {
            wchar_t* end = nullptr;
            const auto parsed = std::wcstoull(argv[++i], &end, 10);
            if (end == argv[i] || *end || !parsed || parsed > MAXDWORD) return 2;
            targetPid = static_cast<DWORD>(parsed);
        } else {
            std::fprintf(stderr, "usage: list_audio_sessions [--seconds 0..3600] [--target-pid PID]\n");
            return 2;
        }
    }
    if (FAILED(CoInitializeEx(nullptr, COINIT_MULTITHREADED))) return 1;
    int result = [&] {
        ComPtr<IMMDeviceEnumerator> devices;
        ComPtr<IMMDevice> endpoint;
        ComPtr<IAudioSessionManager2> manager;
        ComPtr<IAudioSessionEnumerator> sessions;
        if (FAILED(CoCreateInstance(__uuidof(MMDeviceEnumerator), nullptr, CLSCTX_ALL, IID_PPV_ARGS(&devices))) ||
            FAILED(devices->GetDefaultAudioEndpoint(eRender, eConsole, &endpoint)) ||
            FAILED(endpoint->Activate(__uuidof(IAudioSessionManager2), CLSCTX_ALL, nullptr, &manager))) return 1;
        // Pin this endpoint for the observation; a default-device switch is not
        // silently treated as the same recording. This is sampled attribution,
        // not process-isolated PCM and not proof of silence between samples.
        LPWSTR endpointId = nullptr;
        if (FAILED(endpoint->GetId(&endpointId))) return 1;
        std::printf("endpoint=%ls target_pid=%lu interval_ms=100 scope=sampled-session-peaks\n", endpointId, targetPid);
        CoTaskMemFree(endpointId);
        const auto started = std::chrono::steady_clock::now();
        unsigned long long samples = 0, otherPositiveSamples = 0, targetPositiveSamples = 0;
        do {
        sessions.Reset();
        if (FAILED(manager->GetSessionEnumerator(&sessions))) return 1;
        const auto unixMs = std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::system_clock::now().time_since_epoch()).count();
        const double elapsed = std::chrono::duration<double>(std::chrono::steady_clock::now() - started).count();
        bool otherPositive = false, targetPositive = false;
        int count = 0;
        if (FAILED(sessions->GetCount(&count))) return 1;
        for (int i = 0; i < count; ++i) {
            ComPtr<IAudioSessionControl> control;
            ComPtr<IAudioSessionControl2> details;
            ComPtr<ISimpleAudioVolume> volume;
            ComPtr<IAudioMeterInformation> meter;
            DWORD pid = 0;
            AudioSessionState state{};
            float level = -1, peak = -1; BOOL mute = FALSE;
            if (FAILED(sessions->GetSession(i, &control)) || FAILED(control.As(&details)) ||
                FAILED(details->GetProcessId(&pid)) || FAILED(control->GetState(&state))) return 1;
            if (SUCCEEDED(control.As(&volume))) {
                if (FAILED(volume->GetMasterVolume(&level)) || FAILED(volume->GetMute(&mute))) return 1;
            }
            if (SUCCEEDED(control.As(&meter)) && FAILED(meter->GetPeakValue(&peak))) return 1;
            wchar_t path[32768] = L"unknown";
            if (pid) {
                HANDLE process = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid);
                if (process) {
                    DWORD length = 32768;
                    QueryFullProcessImageNameW(process, 0, path, &length);
                    CloseHandle(process);
                }
            } else wcscpy_s(path, L"system-sounds");
            const bool positive = state == AudioSessionStateActive && !mute && level > 0 && peak > 0.00001f;
            if (positive) {
                if (targetPid && pid == targetPid) targetPositive = true;
                else otherPositive = true;
            }
            std::printf("sample=%llu unix_ms=%lld elapsed=%.6f session=%d pid=%lu state=%d level=%.6f mute=%d peak=%.6f positive=%d path=%ls\n",
                        samples, static_cast<long long>(unixMs), elapsed, i, pid, static_cast<int>(state), level, mute, peak, positive, path);
        }
        ++samples;
        otherPositiveSamples += otherPositive;
        targetPositiveSamples += targetPositive;
        if (std::chrono::duration<double>(std::chrono::steady_clock::now() - started).count() >= seconds) break;
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
        } while (true);
        std::printf("summary samples=%llu target_positive_samples=%llu other_positive_samples=%llu complete=1 silence_between_samples_unverified=1\n",
                    samples, targetPositiveSamples, otherPositiveSamples);
        return 0;
    }();
    CoUninitialize();
    return result;
}

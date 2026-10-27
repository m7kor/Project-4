// Read-only Windows playback/session inspection. Never changes volume or mute.
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <mmdeviceapi.h>
#include <audiopolicy.h>
#include <endpointvolume.h>
#include <wrl/client.h>
#include <cstdio>
#include <cwchar>
#include <algorithm>
#include <chrono>
#include <thread>
using Microsoft::WRL::ComPtr;

int wmain(int argc, wchar_t** argv)
{
    int seconds = 10;
    if (argc == 3 && !std::wcscmp(argv[1], L"--seconds"))
    {
        wchar_t* end = nullptr;
        const long parsed = std::wcstol(argv[2], &end, 10);
        if (end == argv[2] || *end || parsed < 1 || parsed > 60) return 2;
        seconds = static_cast<int>(parsed);
    }
    else if (argc != 1) return 2;
    if (FAILED(CoInitializeEx(nullptr, COINIT_MULTITHREADED))) return 1;
    int result = [&] {
        ComPtr<IMMDeviceEnumerator> devices;
        if (FAILED(CoCreateInstance(__uuidof(MMDeviceEnumerator), nullptr, CLSCTX_ALL, IID_PPV_ARGS(&devices)))) return 1;
        ComPtr<IMMDevice> endpoint;
        if (FAILED(devices->GetDefaultAudioEndpoint(eRender, eConsole, &endpoint))) return 1;
        LPWSTR id = nullptr;
        if (SUCCEEDED(endpoint->GetId(&id)))
        {
            std::wprintf(L"Default console playback endpoint: %ls\n", id);
            CoTaskMemFree(id);
        }
        ComPtr<IAudioEndpointVolume> volume;
        if (SUCCEEDED(endpoint->Activate(__uuidof(IAudioEndpointVolume), CLSCTX_ALL, nullptr, &volume)))
        {
            float level = -1; BOOL mute = FALSE;
            if (SUCCEEDED(volume->GetMasterVolumeLevelScalar(&level)) && SUCCEEDED(volume->GetMute(&mute)))
                std::printf("Endpoint volume=%.6f mute=%d\n", level, mute);
        }
        ComPtr<IAudioSessionManager2> manager;
        ComPtr<IAudioSessionEnumerator> sessions;
        if (SUCCEEDED(endpoint->Activate(__uuidof(IAudioSessionManager2), CLSCTX_ALL, nullptr, &manager)) &&
            SUCCEEDED(manager->GetSessionEnumerator(&sessions)))
        {
            int count = 0;
            if (FAILED(sessions->GetCount(&count))) return 1;
            for (int i = 0; i < count; ++i)
            {
                ComPtr<IAudioSessionControl> control;
                ComPtr<IAudioSessionControl2> details;
                ComPtr<ISimpleAudioVolume> sessionVolume;
                if (FAILED(sessions->GetSession(i, &control))) continue;
                DWORD pid = 0; AudioSessionState state = AudioSessionStateExpired;
                control->GetState(&state);
                if (SUCCEEDED(control.As(&details))) details->GetProcessId(&pid);
                float level = -1; BOOL mute = FALSE;
                if (SUCCEEDED(control.As(&sessionVolume)))
                {
                    sessionVolume->GetMasterVolume(&level);
                    sessionVolume->GetMute(&mute);
                }
                std::printf("Session pid=%lu state=%d volume=%.6f mute=%d\n", pid, int(state), level, mute);
            }
        }
        ComPtr<IAudioMeterInformation> meter;
        if (FAILED(endpoint->Activate(__uuidof(IAudioMeterInformation), CLSCTX_ALL, nullptr, &meter))) return 1;
        const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(seconds);
        unsigned samples = 0, audible = 0;
        float peak = 0;
        while (std::chrono::steady_clock::now() < deadline)
        {
            float value = 0;
            if (FAILED(meter->GetPeakValue(&value))) return 1;
            ++samples; if (value > 0.0001f) ++audible;
            peak = std::max(peak, value);
            std::this_thread::sleep_for(std::chrono::milliseconds(100));
        }
        std::printf("Endpoint meter samples=%u above_threshold=%u peak=%.8f; read-only\n", samples, audible, peak);
        return 0;
    }();
    CoUninitialize();
    return result;
}

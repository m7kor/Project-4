// Restore only sessions belonging to the explicitly named executable.
#include <windows.h>
#include <mmdeviceapi.h>
#include <audiopolicy.h>
#include <endpointvolume.h>
#include <wrl/client.h>
#include <cstdio>
#include <cwchar>
using Microsoft::WRL::ComPtr;
int wmain(int argc, wchar_t** argv) {
    if (argc != 2) return 2;
    wchar_t target[32768];
    if (!GetFullPathNameW(argv[1], 32768, target, nullptr)) return 2;
    if (FAILED(CoInitializeEx(nullptr, COINIT_MULTITHREADED))) return 1;
    int result = [&] {
        ComPtr<IMMDeviceEnumerator> devices;
        ComPtr<IMMDevice> endpoint;
        ComPtr<IAudioEndpointVolume> master;
        ComPtr<IAudioSessionManager2> manager;
        ComPtr<IAudioSessionEnumerator> sessions;
        if (FAILED(CoCreateInstance(__uuidof(MMDeviceEnumerator), nullptr, CLSCTX_ALL, IID_PPV_ARGS(&devices))) ||
            FAILED(devices->GetDefaultAudioEndpoint(eRender, eConsole, &endpoint)) ||
            FAILED(endpoint->Activate(__uuidof(IAudioEndpointVolume), CLSCTX_ALL, nullptr, &master)) ||
            FAILED(endpoint->Activate(__uuidof(IAudioSessionManager2), CLSCTX_ALL, nullptr, &manager)) ||
            FAILED(manager->GetSessionEnumerator(&sessions))) return 1;
        float beforeMaster = 0; BOOL beforeMute = FALSE;
        if (FAILED(master->GetMasterVolumeLevelScalar(&beforeMaster)) || FAILED(master->GetMute(&beforeMute))) return 1;
        int count = 0, matched = 0;
        if (FAILED(sessions->GetCount(&count))) return 1;
        for (int i = 0; i < count; ++i) {
            ComPtr<IAudioSessionControl> control;
            ComPtr<IAudioSessionControl2> details;
            ComPtr<ISimpleAudioVolume> volume;
            DWORD pid = 0;
            if (FAILED(sessions->GetSession(i, &control)) || FAILED(control.As(&details)) ||
                FAILED(details->GetProcessId(&pid)) || !pid) continue;
            HANDLE process = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid);
            if (!process) continue;
            wchar_t path[32768]; DWORD length = 32768;
            BOOL valid = QueryFullProcessImageNameW(process, 0, path, &length);
            CloseHandle(process);
            if (!valid || _wcsicmp(path, target) || FAILED(control.As(&volume))) continue;
            float before = 0, after = 0; BOOL mute = FALSE, afterMute = FALSE;
            if (FAILED(volume->GetMasterVolume(&before)) || FAILED(volume->GetMute(&mute))) return 1;
            // Preserve a nonzero app level; zero sessions use the game's existing 8% level.
            if ((before == 0 && FAILED(volume->SetMasterVolume(0.08f, nullptr))) ||
                FAILED(volume->SetMute(FALSE, nullptr)) || FAILED(volume->GetMasterVolume(&after)) ||
                FAILED(volume->GetMute(&afterMute))) return 1;
            std::wprintf(L"Matched pid=%lu path=%ls before=%.6f mute=%d after=%.6f mute=%d\n",
                pid, path, before, mute, after, afterMute);
            if (after <= 0 || afterMute) return 1;
            ++matched;
        }
        float afterMaster = 0; BOOL afterMute = FALSE;
        if (FAILED(master->GetMasterVolumeLevelScalar(&afterMaster)) || FAILED(master->GetMute(&afterMute))) return 1;
        std::printf("Endpoint before=%.6f mute=%d after=%.6f mute=%d matched=%d\n",
            beforeMaster, beforeMute, afterMaster, afterMute, matched);
        if (beforeMaster != afterMaster || beforeMute != afterMute) return 1;
        return matched ? 0 : 3;
    }();
    CoUninitialize(); return result;
}

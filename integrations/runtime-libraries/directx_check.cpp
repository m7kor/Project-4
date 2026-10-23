#include <directx/d3dx12.h>
#include <cstdio>
bool check_directx() {
    const auto resource = CD3DX12_RESOURCE_DESC::Tex2D(DXGI_FORMAT_R8G8B8A8_UNORM, 64, 32);
    const GUID& device = IID_ID3D12Device;
    const bool okay = resource.Width == 64 && resource.Height == 32 && device.Data1 != 0;
    std::printf("directx_headers=ok resource=64x32 device_iid=%08lx\n", static_cast<unsigned long>(device.Data1));
    return okay;
}

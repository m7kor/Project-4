extern "C" {
#include <libavcodec/avcodec.h>
#include <libavformat/avformat.h>
#include <libavutil/avutil.h>
#include <libswresample/swresample.h>
#include <libswscale/swscale.h>
}
#include <cstdio>
#include <cstring>
bool check_ffmpeg() {
    const AVCodec* decoder = avcodec_find_decoder(AV_CODEC_ID_MPEG2VIDEO);
    AVCodecContext* context = decoder ? avcodec_alloc_context3(decoder) : nullptr;
    const bool opened = context && avcodec_open2(context, decoder, nullptr) == 0;
    avcodec_free_context(&context);
    const char* config = avcodec_configuration();
    const bool shared_lgpl = !std::strstr(config, "--enable-gpl") && !std::strstr(config, "--enable-nonfree");
    std::printf("ffmpeg=%s mpeg2_decoder=%s license=%s avformat=%u swresample=%u swscale=%u\n",
        av_version_info(), opened ? "ok" : "failed", avcodec_license(), avformat_version(), swresample_version(), swscale_version());
    return opened && shared_lgpl && avformat_version() && swresample_version() && swscale_version();
}

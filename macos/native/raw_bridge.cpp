#include "raw_info.h"
#include <libraw/libraw.h>
#include <algorithm>
#include <cstring>
#include <string>
#include <vector>

struct Handle {
    LibRaw raw;
    std::string error;
    std::vector<uint16_t> visible;
    int check(int status) {
        error = status ? libraw_strerror(status) : "";
        return status;
    }
};
extern "C" {
uint32_t srhq_joraw2_abi_version() { return 1; }
const char* srhq_joraw2_build_id() { return "jsr-macos-arm64-libraw-0.22.2-nikon-he"; }
const char* srhq_joraw2_libraw_version() { return LibRaw::version(); }
void* srhq_joraw2_create() { return new Handle(); }
void srhq_joraw2_destroy(void* p) { delete static_cast<Handle*>(p); }
const char* srhq_joraw2_last_error(void* p) { return static_cast<Handle*>(p)->error.c_str(); }
int srhq_joraw2_open_buffer(void* p, void* data, size_t length) {
    auto& h = *static_cast<Handle*>(p);
    return h.check(h.raw.open_buffer(data, length));
}
int srhq_joraw2_unpack(void* p) {
    auto& h = *static_cast<Handle*>(p);
    return h.check(h.raw.unpack());
}
int srhq_joraw2_get_info(void* p, RawInfoV1* info) {
    auto& r = static_cast<Handle*>(p)->raw;
    auto& d = r.imgdata; auto& s = d.sizes; auto& c = d.color;
    std::memset(info, 0, sizeof(*info));
    info->abi_version = 1; info->struct_size = sizeof(*info);
    info->raw_width=s.raw_width; info->raw_height=s.raw_height;
    info->width=s.width; info->height=s.height;
    info->top_margin=s.top_margin; info->left_margin=s.left_margin; info->flip=s.flip;
    info->filters=d.idata.filters; info->colors=d.idata.colors;
    info->maximum=c.maximum; info->data_maximum=c.data_maximum;
    info->raw_bps=c.raw_bps; info->black_common=c.black;
    info->repeat_rows=c.cblack[4]; info->repeat_cols=c.cblack[5];
    info->repeat_count=info->repeat_rows*info->repeat_cols;
    info->repeat_origin_y=s.top_margin; info->repeat_origin_x=s.left_margin;
    for (unsigned i=0;i<4;i++) {
        int y=i/2, x=i%2, color=r.COLOR(y+s.top_margin,x+s.left_margin);
        info->site_color_indices[i]=color;
        info->cblack[i]=c.cblack[i];
        info->black_site_base[i]=c.black+c.cblack[color];
        float repeat=info->repeat_count ? c.cblack[6+((y+s.top_margin)%info->repeat_rows)*info->repeat_cols+(x+s.left_margin)%info->repeat_cols] : 0;
        info->black_site[i]=info->black_site_base[i]+repeat;
        info->cam_mul[i]=c.cam_mul[i]; info->pre_mul[i]=c.pre_mul[i];
        info->cfa_pattern[i]=d.idata.cdesc[color];
    }
    std::memcpy(info->cam_xyz,c.cam_xyz,sizeof(info->cam_xyz));
    std::memcpy(info->cmatrix,c.cmatrix,sizeof(info->cmatrix));
    std::memcpy(info->rgb_cam,c.rgb_cam,sizeof(info->rgb_cam));
    std::snprintf(info->camera_make,sizeof(info->camera_make),"%s",d.idata.make);
    std::snprintf(info->camera_model,sizeof(info->camera_model),"%s",d.idata.model);
    std::snprintf(info->unique_camera_model,sizeof(info->unique_camera_model),"%s %s",d.idata.make,d.idata.model);
    std::snprintf(info->libraw_version,sizeof(info->libraw_version),"%s",LibRaw::version());
    std::snprintf(info->build_id,sizeof(info->build_id),"%s",srhq_joraw2_build_id());
    return 0;
}
int srhq_joraw2_get_capture_info(void* p,double* iso,double* shutter,int64_t* timestamp) {
    auto& o=static_cast<Handle*>(p)->raw.imgdata.other;
    *iso=o.iso_speed; *shutter=o.shutter; *timestamp=static_cast<int64_t>(o.timestamp); return 0;
}
size_t srhq_joraw2_black_repeat_count(void* p) {
    auto& c=static_cast<Handle*>(p)->raw.imgdata.color;return c.cblack[4]*c.cblack[5];
}
int srhq_joraw2_copy_black_repeat(void* p,uint16_t* dst,size_t count) {
    auto& c=static_cast<Handle*>(p)->raw.imgdata.color;
    size_t n=srhq_joraw2_black_repeat_count(p); if(count<n)return -1;
    for(size_t i=0;i<n;i++)dst[i]=c.cblack[6+i]; return 0;
}
const uint16_t* srhq_joraw2_visible_u16_pointer(void* p,size_t* stride) {
    auto& h=*static_cast<Handle*>(p); auto& d=h.raw.imgdata;auto& s=d.sizes;
    if(!d.rawdata.raw_image)return nullptr;
    *stride=s.raw_pitch/sizeof(uint16_t);
    return d.rawdata.raw_image+s.top_margin*(*stride)+s.left_margin;
}
int srhq_joraw2_copy_visible_u16(void* p,uint16_t* dst,size_t count) {
    auto& s=static_cast<Handle*>(p)->raw.imgdata.sizes;
    if(count<size_t(s.width)*s.height)return -1;
    size_t stride=0;auto src=srhq_joraw2_visible_u16_pointer(p,&stride);if(!src)return -1;
    for(unsigned y=0;y<s.height;y++)std::copy_n(src+y*stride,s.width,dst+y*s.width);return 0;
}
}

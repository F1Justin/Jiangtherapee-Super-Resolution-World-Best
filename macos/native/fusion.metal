#include <metal_stdlib>
using namespace metal;

struct TapParams {
    uint n, m, nf, mf, h, w, k, total;
    float y0, x0, cap, count_scale;
};
struct ImageParams { uint h, w, channels, radius, vertical; };
uint linear(uint2 id) { return id.y * 65536u + id.x; }
int reflect101(int i, int size) {
    if (size == 1) return 0;
    while (i < 0 || i >= size) i = i < 0 ? -i : 2 * size - i - 2;
    return i;
}
float stable_tanh(float x) {
    float e = exp(-2.0f * abs(x));
    return sign(x) * (1.0f - e) / (1.0f + e);
}

kernel void phase_accumulate(device const float *frames [[buffer(0)]], device const int *ci [[buffer(1)]],
    device const float *flow [[buffer(2)]], device const float *fsh [[buffer(3)]],
    device const float *cov [[buffer(4)]], device float *accum [[buffer(5)]],
    constant TapParams &P [[buffer(6)]], uint2 id [[thread_position_in_grid]]) {
    uint idx = linear(id);
    if (idx >= P.total * 3) return;
    uint p = idx / 3, c = idx % 3;
    float oy = float(p / P.w) / 2.0f + P.y0;
    float ox = float(p % P.w) / 2.0f + P.x0;
    uint iy0 = uint(clamp(int(oy), 0, int(P.n) - 1));
    uint ix0 = uint(clamp(int(ox), 0, int(P.m) - 1));
    uint base = p * 150 + c * 48, tail = p * 150 + 144, cb = p * 3;
    float an[16], as1[16], as2[16];
    for (uint b = 0; b < 16; ++b) { an[b] = accum[base+b]; as1[b] = accum[base+16+b]; as2[b] = accum[base+32+b]; }
    float num = accum[tail+c], den = accum[tail+3+c];
    for (uint k = 0; k < P.k; ++k) {
        uint fb = (k * P.n * P.m + iy0 * P.m + ix0) * 2, sb = k * 4;
        float my = oy + flow[fb+1] + fsh[sb], mx = ox + flow[fb] + fsh[sb+1];
        float cy = floor(my), cx = floor(mx);
        for (uint ab = 0; ab < 16; ++ab) {
            float yy = cy + float(ab / 4) - 1.0f, xx = cx + float(ab % 4) - 1.0f;
            uint iy = uint(clamp(int(yy), 0, int(fsh[sb+2])-1));
            uint ix = uint(clamp(int(xx), 0, int(fsh[sb+3])-1));
            uint flat = iy * P.mf + ix;
            if (ci[flat] != int(c)) continue;
            float dy = yy-my, dx = xx-mx;
            float z = cov[cb] * dx * dx + 2.0f * cov[cb+1] * dx * dy + cov[cb+2] * dy * dy;
            float weight = exp(-0.5f*z), value = frames[k * P.nf * P.mf + flat];
            float ry = dy - floor(dy/2.0f)*2.0f, rx = dx - floor(dx/2.0f)*2.0f;
            uint bin = min(uint(ry*0.5f*4.0f), 3u)*4 + min(uint(rx*0.5f*4.0f), 3u);
            an[bin] = an[bin] + weight;
            as1[bin] = as1[bin] + weight * value;
            as2[bin] = as2[bin] + weight * value * value;
            num = num + weight * value; den = den + weight;
        }
    }
    for (uint b = 0; b < 16; ++b) { accum[base+b] = an[b]; accum[base+16+b] = as1[b]; accum[base+32+b] = as2[b]; }
    accum[tail+c] = num; accum[tail+3+c] = den;
}

kernel void phase_finalize(device const float *accum [[buffer(0)]], device float *feature [[buffer(1)]],
    device float *legacy [[buffer(2)]], device atomic_uint *error [[buffer(3)]],
    constant TapParams &P [[buffer(4)]], uint2 id [[thread_position_in_grid]]) {
    uint idx = linear(id);
    if (idx >= P.total * 3) return;
    uint p = idx / 3, c = idx % 3, base = p*150+c*48;
    for (uint b = 0; b < 16; ++b) {
        float count = accum[base+b], den = max(count, 1.0e-9f);
        float mu = accum[base+16+b] / den;
        float variance = max(accum[base+32+b]/den - mu*mu, 0.0f);
        feature[(c*48+b)*P.total+p] = count * P.count_scale;
        feature[(c*48+16+b)*P.total+p] = mu;
        feature[(c*48+32+b)*P.total+p] = sqrt(variance);
    }
    float den = accum[p*150+147+c];
    if (den <= 0) atomic_fetch_or_explicit(error, 1u, memory_order_relaxed);
    float value = precise::divide(accum[p*150+144+c], den);
    legacy[p*3+c] = value;
    feature[(144+c)*P.total+p] = value;
}

float grey(device const float *rgb, uint p) { return 0.299f*rgb[p*3] + 0.587f*rgb[p*3+1] + 0.114f*rgb[p*3+2]; }
kernel void structure_energy(device const float *rgb [[buffer(0)]], device float *energy [[buffer(1)]],
    device float *structure [[buffer(2)]], constant ImageParams &P [[buffer(3)]], uint2 id [[thread_position_in_grid]]) {
    uint p = linear(id), pixels = P.h*P.w;
    if (p >= pixels) return;
    int y = p/P.w, x = p%P.w;
    float gx = 0, gy = 0;
    for (int dy = -1; dy <= 1; ++dy) for (int dx = -1; dx <= 1; ++dx) {
        float g = grey(rgb, uint(reflect101(y+dy, P.h))*P.w + uint(reflect101(x+dx, P.w)));
        float sx = float(dx) * (dy == 0 ? 2.0f : 1.0f), sy = float(dy) * (dx == 0 ? 2.0f : 1.0f);
        gx += g*sx; gy += g*sy;
    }
    structure[p] = gx*gx; structure[pixels+p] = gx*gy; structure[pixels*2+p] = gy*gy;
    energy[p] = (rgb[p*3]*rgb[p*3] + rgb[p*3+1]*rgb[p*3+1] + rgb[p*3+2]*rgb[p*3+2]) / 3.0f;
}

kernel void gaussian(device const float *source [[buffer(0)]], device float *output [[buffer(1)]],
    device const float *coefficients [[buffer(2)]], constant ImageParams &P [[buffer(3)]], uint2 id [[thread_position_in_grid]]) {
    uint i = linear(id), pixels = P.h*P.w;
    if (i >= pixels*P.channels) return;
    uint c = i/pixels, p = i%pixels;
    int y = p/P.w, x = p%P.w;
    float value = 0;
    uint offset = P.radius == 16 ? 0 : 33;
    if (P.vertical) {
        value = source[c*pixels+p] * coefficients[offset+P.radius];
        for (int k=1; k<=int(P.radius); ++k) {
            float pair = source[c*pixels+uint(reflect101(y+k,P.h))*P.w+uint(x)]
                       + source[c*pixels+uint(reflect101(y-k,P.h))*P.w+uint(x)];
            float coefficient = coefficients[offset+P.radius+uint(k)];
            value = x < int(P.w/4*4) ? fma(pair,coefficient,value) : value+pair*coefficient;
        }
    } else {
        for (int k=-int(P.radius); k<=int(P.radius); ++k) {
            float sample = source[c*pixels+uint(y)*P.w+uint(reflect101(x+k,P.w))];
            float coefficient = coefficients[offset+uint(k+int(P.radius))];
            value = x < int(P.w/4*4) ? fma(sample,coefficient,value) : value+sample*coefficient;
        }
    }
    output[i] = value;
}

kernel void normalize_feature(device float *feature [[buffer(0)]], device const float *energy [[buffer(1)]],
    device const float *structure [[buffer(2)]], device const float *coefficients [[buffer(3)]],
    device atomic_uint *error [[buffer(4)]], constant ImageParams &P [[buffer(5)]], uint2 id [[thread_position_in_grid]]) {
    uint i = linear(id), pixels = P.h*P.w;
    if (i >= pixels*151) return;
    uint c = i/pixels, p = i%pixels;
    float a = sqrt(max(energy[p],0.0f)), den = a > 0 ? a : 1.0f;
    uint degree = c < 144 ? (c%48 < 16 ? 0 : 1) : (c < 147 ? 1 : (c < 150 ? 2 : 1));
    float value = c < 147 ? feature[i] : (c < 150 ? structure[(c-147)*pixels+p] : 0.0f);
    if (degree == 1) value = precise::divide(value, den);
    if (degree == 2) value = precise::divide(value, den*den);
    value = precise::divide(value - coefficients[50+c], coefficients[201+c]);
    if (!isfinite(value)) atomic_fetch_or_explicit(error, 2u, memory_order_relaxed);
    feature[i] = value;
}

kernel void validate_qmap(device const float *qmap [[buffer(0)]], device atomic_uint *error [[buffer(1)]],
    constant TapParams &P [[buffer(2)]], uint2 id [[thread_position_in_grid]]) {
    uint i = linear(id);
    if (i < P.total*36 && !isfinite(qmap[i])) atomic_fetch_or_explicit(error, 4u, memory_order_relaxed);
}

kernel void learned_accumulate(device const float *frames [[buffer(0)]], device const int *ci [[buffer(1)]],
    device const float *flow [[buffer(2)]], device const float *fsh [[buffer(3)]],
    device const float *cov [[buffer(4)]], device const float *qmap [[buffer(5)]], device float *accum [[buffer(6)]],
    constant TapParams &P [[buffer(7)]], uint2 id [[thread_position_in_grid]]) {
    uint p = linear(id);
    if (p >= P.total) return;
    float oy = float(p/P.w)/2.0f + P.y0, ox = float(p%P.w)/2.0f + P.x0;
    uint iy0 = uint(clamp(int(oy),0,int(P.n)-1)), ix0 = uint(clamp(int(ox),0,int(P.m)-1)), cb=p*3;
    float num[3], den[3];
    for (uint c=0;c<3;++c) { num[c]=accum[p*6+c];den[c]=accum[p*6+3+c]; }
    for (uint k=0;k<P.k;++k) {
        uint fb=(k*P.n*P.m+iy0*P.m+ix0)*2,sb=k*4;
        float my=oy+flow[fb+1]+fsh[sb],mx=ox+flow[fb]+fsh[sb+1],cy=floor(my),cx=floor(mx);
        for (uint ab=0;ab<16;++ab) {
            float yy=cy+float(ab/4)-1.0f,xx=cx+float(ab%4)-1.0f;
            uint iy=uint(clamp(int(yy),0,int(fsh[sb+2])-1)),ix=uint(clamp(int(xx),0,int(fsh[sb+3])-1));
            uint flat=iy*P.mf+ix,c=uint(ci[flat]),qb=c*12*P.total+p;
            float dy=yy-my,dx=xx-mx,z=cov[cb]*dx*dx+2.0f*cov[cb+1]*dx*dy+cov[cb+2]*dy*dy;
            float r2=dy*dy+dx*dx,raw=0;
            raw=raw+qmap[qb]; raw=raw+qmap[qb+P.total]*dy; raw=raw+qmap[qb+2*P.total]*dx;
            raw=raw+qmap[qb+3*P.total]*dy*dy; raw=raw+qmap[qb+4*P.total]*dx*dx;
            raw=raw+qmap[qb+5*P.total]*dy*dx; raw=raw+qmap[qb+6*P.total]*r2;
            raw=raw+qmap[qb+7*P.total]*r2*r2;
            raw=raw+qmap[qb+8*P.total]*cos(6.2831853071795864769f*dy);
            raw=raw+qmap[qb+9*P.total]*sin(6.2831853071795864769f*dy);
            raw=raw+qmap[qb+10*P.total]*cos(6.2831853071795864769f*dx);
            raw=raw+qmap[qb+11*P.total]*sin(6.2831853071795864769f*dx);
            float delta=P.cap*stable_tanh(raw/P.cap),weight=exp(-0.5f*z+delta),value=frames[k*P.nf*P.mf+flat];
            den[c]=den[c]+weight; num[c]=num[c]+weight*value;
        }
    }
    for(uint c=0;c<3;++c){accum[p*6+c]=num[c];accum[p*6+3+c]=den[c];}
}

kernel void learned_finalize(device const float *accum [[buffer(0)]], device float *output [[buffer(1)]],
    device atomic_uint *error [[buffer(2)]], constant TapParams &P [[buffer(3)]], uint2 id [[thread_position_in_grid]]) {
    uint p=linear(id);
    if(p>=P.total)return;
    for(uint c=0;c<3;++c){float den=accum[p*6+3+c];float value=den>0?accum[p*6+c]/den:0.0f;
        if(!isfinite(value)) atomic_fetch_or_explicit(error,8u,memory_order_relaxed);output[p*3+c]=value;}
}


kernel void validate_output(device const float *legacy [[buffer(0)]], device const float *output [[buffer(1)]],
    device atomic_uint *error [[buffer(2)]], constant TapParams &P [[buffer(3)]], uint2 id [[thread_position_in_grid]]) {
    uint i=linear(id);
    if(i<P.total*3 && (!isfinite(legacy[i]) || !isfinite(output[i])))
        atomic_fetch_or_explicit(error,8u,memory_order_relaxed);
}

#include <vector>
namespace {
struct TapParams { uint32_t n,m,nf,mf,h,w,k,total; float y0,x0,cap,count_scale; };
struct ImageParams { uint32_t h,w,channels,radius,vertical; };
struct Chunk { id<MTLBuffer> frames, cfa, flow, shift; uint32_t k,nf,mf; };
struct Fusion {
    id<MTLDevice> device;
    id<MTLCommandQueue> queue;
    NSDictionary *pipelines;
    id<MTLBuffer> cov, stats, feature, legacy, qmap, accum, output, error;
    id<MTLBuffer> energy, structure, etmp, stmp, efiltered, sfiltered, coefficients;
    NSMutableArray *retained = [NSMutableArray new];
    std::vector<Chunk> chunks;
    TapParams p;
    id<MTLCommandBuffer> last;
    uint64_t uploaded=0, downloaded=0, allocated=0;
    id<MTLBuffer> buffer(size_t count) {
        auto b=[device newBufferWithLength:count*4 options:MTLResourceStorageModeShared];
        if (!b) throw std::runtime_error("Native fusion allocation failed");
        allocated+=b.length; return b;
    }
    id<MTLBuffer> upload(const void *source,size_t count) {
        auto b=buffer(count); memcpy(b.contents,source,count*4); uploaded+=count*4; return b;
    }
    void dispatch(NSString *name, NSArray *buffers, const void *params, size_t bytes, size_t total) {
        auto command=[queue commandBuffer]; auto enc=[command computeCommandEncoder];
        auto pipeline=(id<MTLComputePipelineState>)pipelines[name];
        [enc setComputePipelineState:pipeline];
        for(NSUInteger i=0;i<buffers.count;++i) [enc setBuffer:buffers[i] offset:0 atIndex:i];
        [enc setBytes:params length:bytes atIndex:buffers.count];
        [enc dispatchThreads:MTLSizeMake(std::min(total,size_t(65536)),(total+65535)/65536,1)
            threadsPerThreadgroup:MTLSizeMake(64,1,1)];
        [enc endEncoding]; [command commit]; last=command;
    }
    void zero(NSArray *buffers) {
        auto command=[queue commandBuffer]; auto enc=[command blitCommandEncoder];
        for(id<MTLBuffer> b in buffers) [enc fillBuffer:b range:NSMakeRange(0,b.length) value:0];
        [enc endEncoding]; [command commit]; last=command;
    }
    void wait() {
        [last waitUntilCompleted];
        if(last.status==MTLCommandBufferStatusError) throw std::runtime_error(last.error.localizedDescription.UTF8String);
    }
    ~Fusion() { [last waitUntilCompleted]; }
};
std::mutex fusion_init_lock;
id<MTLCommandQueue> fusion_queue;
NSDictionary *fusion_pipelines;
void init_fusion(const char *source,id<MTLDevice> device) {
#ifdef JSR_EMBEDDED_FUSION
    if (!source) source = jsr_embedded_fusion;
#endif
    if (!source) throw std::runtime_error("Fusion shader is unavailable");
    std::lock_guard<std::mutex> guard(fusion_init_lock);
    if(fusion_pipelines) return;
    // Match the release WGSL lowering for taps; local features use precise CPU-compatible arithmetic.
    NSError *error=nil; auto options=[MTLCompileOptions new]; options.fastMathEnabled=YES; options.preserveInvariance=YES;
    if (@available(macOS 14.0, *)) options.languageVersion=MTLLanguageVersion3_1;
    else options.languageVersion=MTLLanguageVersion3_0;
    auto library=[device newLibraryWithSource:[NSString stringWithUTF8String:source] options:options error:&error];
    if(!library) throw std::runtime_error(error.localizedDescription.UTF8String);
    options.fastMathEnabled=NO;
    auto preciseLibrary=[device newLibraryWithSource:[NSString stringWithUTF8String:source] options:options error:&error];
    if(!preciseLibrary) throw std::runtime_error(error.localizedDescription.UTF8String);
    auto pipelines=[NSMutableDictionary new];
    for(NSString *name in @[@"phase_accumulate",@"phase_finalize",@"structure_energy",@"gaussian",
                           @"normalize_feature",@"validate_qmap",@"learned_accumulate",@"learned_finalize",@"validate_output"]) {
        bool frontend=[@[@"structure_energy",@"gaussian",@"normalize_feature",@"validate_qmap",@"validate_output"] containsObject:name];
        auto pipeline=[device newComputePipelineStateWithFunction:[(frontend?preciseLibrary:library) newFunctionWithName:name] error:&error];
        if(!pipeline) throw std::runtime_error(error.localizedDescription.UTF8String);
        pipelines[name]=pipeline;
    }
    fusion_queue=[device newCommandQueue]; fusion_pipelines=pipelines;
}
}
#define FUSION_TRY @autoreleasepool { @try { try {
#define FUSION_END } catch(const std::exception &e) { last_error=e.what(); return -1; } } @catch(NSException *e) { last_error=e.reason.UTF8String; return -1; } }
extern "C" void *jsr_fusion_create(const char *shader,const float *cov,int y,int x,int h,int w,int n,int m) {
    @autoreleasepool { @try { try {
        auto owner=std::make_unique<Fusion>(); auto f=owner.get();
        f->device=MTLCreateSystemDefaultDevice(); init_fusion(shader,f->device);
        f->queue=fusion_queue; f->pipelines=fusion_pipelines;
        if(h<=0||w<=0||n<=0||m<=0) throw std::runtime_error("Invalid fusion dimensions");
        uint32_t pixels=uint32_t(h)*2*uint32_t(w)*2;
        f->p={uint32_t(n),uint32_t(m),0,0,uint32_t(h)*2,uint32_t(w)*2,0,pixels,float(y),float(x),5,1};
        f->cov=f->upload(cov,pixels*3); f->stats=f->buffer(pixels*150); f->feature=f->buffer(pixels*151);
        f->legacy=f->buffer(pixels*3); f->qmap=f->buffer(pixels*36); f->accum=f->buffer(pixels*6);
        f->output=f->buffer(pixels*3); f->error=f->buffer(1);
        f->energy=f->buffer(pixels); f->structure=f->buffer(pixels*3);
        f->etmp=f->buffer(pixels); f->stmp=f->buffer(pixels*3);
        f->efiltered=f->buffer(pixels); f->sfiltered=f->buffer(pixels*3);
        f->zero(@[f->stats,f->accum,f->error]); return owner.release();
    } catch(const std::exception &e) {last_error=e.what();return nullptr;}
    } @catch(NSException *e) {last_error=e.reason.UTF8String;return nullptr;} }
}
extern "C" int jsr_fusion_phase(void *handle,const float *frames,const int32_t *cfa,const float *flow,const float *shift,int k,int nf,int mf) {
    FUSION_TRY
    auto f=static_cast<Fusion *>(handle); auto p=f->p; p.k=k;p.nf=nf;p.mf=mf;
    Chunk c={f->upload(frames,size_t(k)*nf*mf),f->upload(cfa,size_t(nf)*mf),
        f->upload(flow,size_t(k)*p.n*p.m*2),f->upload(shift,k*4),uint32_t(k),uint32_t(nf),uint32_t(mf)};
    f->chunks.push_back(c);
    f->dispatch(@"phase_accumulate",@[c.frames,c.cfa,c.flow,c.shift,f->cov,f->stats],&p,sizeof(p),p.total*3);
    return 0; FUSION_END
}
extern "C" int jsr_fusion_finalize_phase(void *handle,int k) {
    FUSION_TRY
    auto f=static_cast<Fusion *>(handle); auto p=f->p;p.count_scale=14.0f/k;
    f->dispatch(@"phase_finalize",@[f->stats,f->feature,f->legacy,f->error],&p,sizeof(p),p.total*3);
    return 0; FUSION_END
}
extern "C" int jsr_fusion_frontend(void *handle,const float *coefficients) {
    FUSION_TRY
    auto f=static_cast<Fusion *>(handle);f->coefficients=f->upload(coefficients,352);
    ImageParams p={f->p.h,f->p.w,1,0,0};
    f->dispatch(@"structure_energy",@[f->legacy,f->energy,f->structure],&p,sizeof(p),f->p.total);
    for(int structure=0;structure<2;++structure) {
        p.channels=structure?3:1;p.radius=structure?8:16;p.vertical=0;
        auto source=structure?f->structure:f->energy, tmp=structure?f->stmp:f->etmp, out=structure?f->sfiltered:f->efiltered;
        f->dispatch(@"gaussian",@[source,tmp,f->coefficients],&p,sizeof(p),f->p.total*p.channels);
        p.vertical=1;f->dispatch(@"gaussian",@[tmp,out,f->coefficients],&p,sizeof(p),f->p.total*p.channels);
    }
    f->dispatch(@"normalize_feature",@[f->feature,f->efiltered,f->sfiltered,f->coefficients,f->error],&p,sizeof(p),f->p.total*151);
    return 0; FUSION_END
}
extern "C" int jsr_fusion_controller(void *handle,void *graph_handle) {
    FUSION_TRY
    auto f=static_cast<Fusion *>(handle);auto e=static_cast<Engine *>(graph_handle);
    std::lock_guard<std::mutex> guard(e->lock);
    if(!e->controller || e->device.registryID!=f->device.registryID) throw std::runtime_error("Native Controller device mismatch");
    e->select(1,f->p.h,f->p.w);
    auto feed=[[MPSGraphTensorData alloc] initWithMTLBuffer:f->feature shape:e->input.shape dataType:MPSDataTypeFloat32];
    auto result=[[MPSGraphTensorData alloc] initWithMTLBuffer:f->qmap shape:e->output.shape dataType:MPSDataTypeFloat32];
    auto outputs=[e->executable runAsyncWithMTLCommandQueue:f->queue inputsArray:@[feed] resultsArray:@[result] executionDescriptor:nil];
    [f->retained addObject:feed];[f->retained addObjectsFromArray:outputs];
    NSString *key=[NSString stringWithFormat:@"1,%u,%u",f->p.h,f->p.w];
    e->shape_calls[key]=@([e->shape_calls[key] unsignedLongLongValue]+1);
    f->dispatch(@"validate_qmap",@[f->qmap,f->error],&f->p,sizeof(f->p),f->p.total*36);
    return 0; FUSION_END
}
extern "C" int jsr_fusion_learned(void *handle,int index,float cap) {
    FUSION_TRY
    auto f=static_cast<Fusion *>(handle);const auto &c=f->chunks.at(index);auto p=f->p;
    p.k=c.k;p.nf=c.nf;p.mf=c.mf;p.cap=cap;
    f->dispatch(@"learned_accumulate",@[c.frames,c.cfa,c.flow,c.shift,f->cov,f->qmap,f->accum],&p,sizeof(p),p.total);
    return 0; FUSION_END
}
extern "C" int jsr_fusion_finish(void *handle,float *legacy,float *output) {
    FUSION_TRY
    auto f=static_cast<Fusion *>(handle);
    f->dispatch(@"learned_finalize",@[f->accum,f->output,f->error],&f->p,sizeof(f->p),f->p.total);
    f->dispatch(@"validate_output",@[f->legacy,f->output,f->error],&f->p,sizeof(f->p),f->p.total*3);f->wait();
    if(*static_cast<uint32_t *>(f->error.contents)) throw std::runtime_error("Native fusion validation flags: "+std::to_string(*static_cast<uint32_t *>(f->error.contents)));
    memcpy(legacy,f->legacy.contents,f->p.total*3*4);memcpy(output,f->output.contents,f->p.total*3*4);
    f->downloaded+=f->p.total*6*4; return 0; FUSION_END
}
extern "C" int jsr_fusion_debug(void *handle,int tensor,float *destination) {
    FUSION_TRY
    auto f=static_cast<Fusion *>(handle);f->wait();
    id<MTLBuffer> b=tensor==0?f->feature:(tensor==1?f->legacy:f->qmap);
    memcpy(destination,b.contents,b.length); return 0; FUSION_END
}
extern "C" int jsr_fusion_debug_qmap(void *handle,const float *source) {
    FUSION_TRY
    auto f=static_cast<Fusion *>(handle);f->wait();
    memcpy(f->qmap.contents,source,f->qmap.length);f->uploaded+=f->qmap.length;return 0; FUSION_END
}
extern "C" const char *jsr_fusion_metrics(void *handle) {
    @autoreleasepool {
        auto f=static_cast<Fusion *>(handle);
        auto data=[NSJSONSerialization dataWithJSONObject:@{@"uploaded_bytes":@(f->uploaded),@"downloaded_bytes":@(f->downloaded),
           @"allocated_bytes":@(f->allocated),@"chunks":@(f->chunks.size())} options:0 error:nil];
        static thread_local std::string encoded;encoded.assign(static_cast<const char *>(data.bytes),data.length);return encoded.c_str();
    }
}
extern "C" void jsr_fusion_destroy(void *handle) { @autoreleasepool { delete static_cast<Fusion *>(handle); } }
#undef FUSION_TRY
#undef FUSION_END

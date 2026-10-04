#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#import <MetalPerformanceShadersGraph/MetalPerformanceShadersGraph.h>
#include <mutex>
#include <memory>
#include <string>
#include <stdexcept>
#include <cstring>
#include <list>
#include <chrono>

namespace {
thread_local std::string last_error;
using Clock = std::chrono::steady_clock;
double seconds(Clock::time_point start) {
    return std::chrono::duration<double>(Clock::now() - start).count();
}
struct Plan {
    MPSGraph *graph;
    MPSGraphTensor *input, *output;
    MPSGraphExecutable *executable;
    id<MTLBuffer> source;
    MPSGraphTensorData *feed;
    int n, h, w;
    uint64_t estimate;
};
struct Engine {
    id<MTLDevice> device;
    id<MTLCommandQueue> queue;
    NSDictionary *weights;
    MPSGraph *graph;
    MPSGraphTensor *input;
    MPSGraphTensor *output;
    MPSGraphExecutable *executable;
    id<MTLBuffer> source_buffer;
    MPSGraphTensorData *feed;
    int batch = 0, height = 0, width = 0;
    bool controller = false;
    std::list<Plan> plans;
    size_t cache_capacity = 1;
    uint64_t cache_budget = UINT64_MAX;
    uint64_t hits = 0, misses = 0, evictions = 0, input_bytes = 0, output_bytes = 0;
    double build_seconds = 0, copy_seconds = 0, run_readback_seconds = 0;
    NSMutableDictionary *shape_calls = [NSMutableDictionary new];
    std::mutex lock;

    void clear_current() {
        executable = nil; input = nil; output = nil; feed = nil; source_buffer = nil; graph = nil;
        batch = height = width = 0;
    }
    uint64_t cached_bytes() const {
        uint64_t sum = 0;
        for (const auto &plan : plans) sum += plan.estimate;
        return sum;
    }
    void select(int n, int h, int w) {
        for (auto it = plans.begin(); it != plans.end(); ++it) {
            if (it->n != n || it->h != h || it->w != w) continue;
            plans.splice(plans.begin(), plans, it);
            const auto &plan = plans.front();
            graph = plan.graph; input = plan.input; output = plan.output; executable = plan.executable;
            source_buffer = plan.source; feed = plan.feed;
            batch = n; height = h; width = w; ++hits;
            return;
        }
        ++misses;
        auto base = [weights[controller ? @"enc.0.0.weight" : @"inp.weight"][@"shape"][0] unsignedLongLongValue];
        uint64_t estimate = uint64_t(n) * h * w * ((controller ? 187 : 9) + base * 8) * 4;
        clear_current();
        while (!plans.empty() && (plans.size() >= cache_capacity || cached_bytes() + estimate > cache_budget)) {
            plans.pop_back(); ++evictions;
        }
        auto start = Clock::now();
        build(n, h, w);
        build_seconds += seconds(start);
        plans.push_front({graph, input, output, executable, source_buffer, feed, n, h, w, estimate});
    }

    MPSGraphTensor *scalar(double x) {
        return [graph constantWithScalar:x dataType:MPSDataTypeFloat32];
    }
    MPSGraphTensor *add(MPSGraphTensor *a, MPSGraphTensor *b) {
        return [graph additionWithPrimaryTensor:a secondaryTensor:b name:nil];
    }
    MPSGraphTensor *mul(MPSGraphTensor *a, MPSGraphTensor *b) {
        return [graph multiplicationWithPrimaryTensor:a secondaryTensor:b name:nil];
    }
    MPSGraphTensor *div(MPSGraphTensor *a, MPSGraphTensor *b) {
        return [graph divisionWithPrimaryTensor:a secondaryTensor:b name:nil];
    }
    MPSGraphTensor *gelu(MPSGraphTensor *x) {
        auto z = mul(x, scalar(0.70710678118654752440));
        auto a = [graph absoluteWithTensor:z name:nil];
        auto t = div(scalar(1.0), add(scalar(1.0), mul(scalar(0.3275911), a)));
        auto poly = add(mul(scalar(1.061405429), t), scalar(-1.453152027));
        poly = add(mul(poly, t), scalar(1.421413741));
        poly = add(mul(poly, t), scalar(-0.284496736));
        poly = add(mul(poly, t), scalar(0.254829592));
        auto e = [graph exponentWithTensor:mul(scalar(-1.0), mul(a, a)) name:nil];
        auto erf = mul([graph signWithTensor:z name:nil], add(scalar(1.0), mul(scalar(-1.0), mul(mul(poly, t), e))));
        return mul(mul(scalar(0.5), x), add(scalar(1.0), erf));
    }
    MPSGraphTensor *stable_tanh(MPSGraphTensor *x) {
        auto e = [graph exponentWithTensor:mul(scalar(-2.0), [graph absoluteWithTensor:x name:nil]) name:nil];
        return mul([graph signWithTensor:x name:nil], div(add(scalar(1.0), mul(scalar(-1.0), e)), add(scalar(1.0), e)));
    }
    MPSGraphTensor *constant(NSString *name) {
        NSDictionary *entry = weights[name];
        if (!entry) throw std::runtime_error("Missing model tensor");
        return [graph constantWithData:entry[@"data"] shape:entry[@"shape"] dataType:MPSDataTypeFloat32];
    }
    MPSGraphTensor *conv(MPSGraphTensor *source, NSString *prefix, bool preact = false) {
        NSString *key = [prefix stringByAppendingString:@".weight"];
        if ([weights[key][@"zero"] boolValue])
            return constant([prefix stringByAppendingString:@".bias"]);
        NSArray *shape = weights[key][@"shape"];
        NSUInteger ks = [shape[2] unsignedIntegerValue];
        auto wt = [graph transposeTensor:constant(key) permutation:@[@2, @3, @1, @0] name:nil];
        auto descriptor = [MPSGraphConvolution2DOpDescriptor descriptorWithStrideInX:1 strideInY:1
            dilationRateInX:1 dilationRateInY:1 groups:1 paddingLeft:ks/2 paddingRight:ks/2
            paddingTop:ks/2 paddingBottom:ks/2 paddingStyle:MPSGraphPaddingStyleExplicit
            dataLayout:MPSGraphTensorNamedDataLayoutNHWC weightsLayout:MPSGraphTensorNamedDataLayoutHWIO];
        auto result = [graph convolution2DWithSourceTensor:preact ? gelu(source) : source
            weightsTensor:wt descriptor:descriptor name:nil];
        return add(result, constant([prefix stringByAppendingString:@".bias"]));
    }
    void build(int n, int h, int w) {
        executable = nil;
        input = nil; output = nil; feed = nil; source_buffer = nil; graph = nil;
        graph = [MPSGraph new];
        input = [graph placeholderWithShape:@[@(n), controller ? @151 : @6, @(h), @(w)] dataType:MPSDataTypeFloat32 name:@"input"];
        auto source = [graph transposeTensor:input permutation:@[@0, @2, @3, @1] name:nil];
        MPSGraphTensor *result;
        if (controller) {
            NSMutableArray<MPSGraphTensor *> *skips = [NSMutableArray new];
            auto pool = [MPSGraphPooling2DOpDescriptor descriptorWithKernelWidth:2 kernelHeight:2
                strideInX:2 strideInY:2 paddingStyle:MPSGraphPaddingStyleExplicit dataLayout:MPSGraphTensorNamedDataLayoutNHWC];
            auto current = source;
            for (int layer = 0; layer < 3; ++layer) {
                current = gelu(conv(current, [NSString stringWithFormat:@"enc.%d.0", layer]));
                current = gelu(conv(current, [NSString stringWithFormat:@"enc.%d.2", layer]));
                [skips addObject:current];
                current = [graph avgPooling2DWithSourceTensor:current descriptor:pool name:nil];
            }
            current = gelu(conv(current, @"mid.0"));
            current = gelu(conv(current, @"mid.2"));
            for (int layer = 0; layer < 3; ++layer) {
                auto skip = skips[2 - layer];
                int32_t size[] = {skip.shape[1].intValue, skip.shape[2].intValue};
                auto shape = [graph constantWithData:[NSData dataWithBytes:size length:sizeof(size)] shape:@[@2] dataType:MPSDataTypeInt32];
                current = [graph resizeTensor:current sizeTensor:shape mode:MPSGraphResizeBilinear
                    centerResult:YES alignCorners:NO layout:MPSGraphTensorNamedDataLayoutNHWC name:nil];
                current = [graph concatTensors:@[current, skip] dimension:3 name:nil];
                current = gelu(conv(current, [NSString stringWithFormat:@"dec.%d.0", layer]));
                current = gelu(conv(current, [NSString stringWithFormat:@"dec.%d.2", layer]));
            }
            result = conv(current, @"out");
        } else {
            auto green = [graph concatTensors:@[
                [graph sliceTensor:source dimension:3 start:1 length:1 name:nil],
                [graph sliceTensor:source dimension:3 start:4 length:1 name:nil]] dimension:3 name:nil];
            bool folded = weights[@"folded_gammas.0.weight"] != nil;
            auto guide = folded ? green : conv(green, @"guide");
            auto current = conv(source, @"inp");
            for (int block = 0; ; ++block) {
                NSString *c1 = [NSString stringWithFormat:@"body.%d.c1", block];
                if (!weights[[c1 stringByAppendingString:@".weight"]]) break;
                auto temp = conv(current, c1, true);
                current = add(current, conv(temp, [NSString stringWithFormat:@"body.%d.c2", block], true));
                auto gamma = conv(guide, [NSString stringWithFormat:folded ? @"folded_gammas.%d" : @"gammas.%d", block]);
                current = mul(current, add(scalar(1.0), mul(scalar(0.1), stable_tanh(gamma))));
                current = add(current, conv(guide, [NSString stringWithFormat:folded ? @"folded_betas.%d" : @"betas.%d", block]));
            }
            result = conv(current, @"out");
        }
        output = [graph transposeTensor:result permutation:@[@0, @3, @1, @2] name:nil];
        auto compilation = [MPSGraphCompilationDescriptor new];
        compilation.optimizationLevel = MPSGraphOptimizationLevel1;
        compilation.waitForCompilationCompletion = YES;
        if (@available(macOS 26.0, *)) compilation.reducedPrecisionFastMath = MPSGraphReducedPrecisionFastMathNone;
        auto type = [[MPSGraphShapedType alloc] initWithShape:input.shape dataType:MPSDataTypeFloat32];
        executable = [graph compileWithDevice:[MPSGraphDevice deviceWithMTLDevice:device]
            feeds:@{input: type} targetTensors:@[output] targetOperations:nil compilationDescriptor:compilation];
        source_buffer = [device newBufferWithLength:size_t(n) * (controller ? 151 : 6) * h * w * sizeof(float)
            options:MTLResourceStorageModeShared];
        if (!source_buffer) throw std::runtime_error("Metal input allocation failed");
        feed = [[MPSGraphTensorData alloc] initWithMTLBuffer:source_buffer shape:input.shape dataType:MPSDataTypeFloat32];
        batch = n; height = h; width = w;
    }
};
}

extern "C" const char *jsr_graph_error() { return last_error.c_str(); }

extern "C" void *jsr_graph_create(const char *manifest, const float *packed) {
    @autoreleasepool { @try { try {
        auto owner = std::make_unique<Engine>();
        auto engine = owner.get();
        engine->device = MTLCreateSystemDefaultDevice();
        if (!engine->device || !engine->device.hasUnifiedMemory) { last_error = "Apple unified-memory Metal device required"; return nullptr; }
        engine->queue = [engine->device newCommandQueue];
        NSData *json = [NSData dataWithBytes:manifest length:strlen(manifest)];
        NSArray *entries = [NSJSONSerialization JSONObjectWithData:json options:0 error:nil];
        NSMutableDictionary *weights = [NSMutableDictionary new];
        for (NSDictionary *entry in entries) {
            NSUInteger count = 1;
            for (NSNumber *dimension in entry[@"shape"]) count *= dimension.unsignedIntegerValue;
            NSData *data = [NSData dataWithBytes:packed + [entry[@"offset"] unsignedIntegerValue] length:count * sizeof(float)];
            weights[entry[@"name"]] = @{@"shape": entry[@"shape"], @"data": data,
                                      @"zero": entry[@"zero"] ?: @NO};
        }
        engine->weights = weights;
        return owner.release();
    } catch (const std::exception &e) { last_error = e.what(); return nullptr; }
    } @catch (NSException *e) { last_error = e.reason.UTF8String; return nullptr; } }
}

extern "C" void *jsr_graph_create_controller(const char *manifest, const float *packed) {
    Engine *engine = static_cast<Engine *>(jsr_graph_create(manifest, packed));
    if (engine) engine->controller = true;
    return engine;
}

extern "C" int jsr_graph_forward(void *handle, const float *source, float *destination, int n, int h, int w) {
    @autoreleasepool { @try { try {
        Engine *engine = static_cast<Engine *>(handle);
        std::lock_guard<std::mutex> guard(engine->lock);
        if (n <= 0 || h <= 0 || w <= 0) throw std::runtime_error("Invalid input dimensions");
        engine->select(n, h, w);
        NSUInteger bytes = size_t(n) * (engine->controller ? 151 : 6) * h * w * sizeof(float);
        auto start = Clock::now();
        memcpy(engine->source_buffer.contents, source, bytes);
        engine->copy_seconds += seconds(start);
        engine->input_bytes += bytes;
        start = Clock::now();
        NSArray<MPSGraphTensorData *> *results = [engine->executable runWithMTLCommandQueue:engine->queue inputsArray:@[engine->feed]
            resultsArray:nil executionDescriptor:nil];
        [results[0].mpsndarray readBytes:destination strideBytes:nil];
        engine->run_readback_seconds += seconds(start);
        engine->output_bytes += size_t(n) * (engine->controller ? 36 : 3) * h * w * sizeof(float);
        NSString *key = [NSString stringWithFormat:@"%d,%d,%d", n, h, w];
        engine->shape_calls[key] = @([engine->shape_calls[key] unsignedLongLongValue] + 1);
        return 0;
    } catch (const std::exception &e) { last_error = e.what(); return -1; }
    } @catch (NSException *e) { last_error = e.reason.UTF8String; return -1; } }
}

extern "C" void jsr_graph_destroy(void *handle) { @autoreleasepool { delete static_cast<Engine *>(handle); } }

extern "C" void jsr_graph_release_workspaces(void *handle) {
    @autoreleasepool {
        auto engine = static_cast<Engine *>(handle);
        std::lock_guard<std::mutex> guard(engine->lock);
        engine->clear_current(); engine->plans.clear();
    }
}

extern "C" void jsr_graph_cache_policy(void *handle, int capacity, uint64_t budget) {
    auto engine = static_cast<Engine *>(handle);
    std::lock_guard<std::mutex> guard(engine->lock);
    engine->cache_capacity = std::max(1, std::min(16, capacity));
    engine->cache_budget = budget;
}

extern "C" const char *jsr_graph_metrics(void *handle) {
    @autoreleasepool {
        auto engine = static_cast<Engine *>(handle);
        std::lock_guard<std::mutex> guard(engine->lock);
        NSDictionary *info = @{@"cache_hits": @(engine->hits), @"cache_misses": @(engine->misses),
            @"cache_evictions": @(engine->evictions), @"cache_capacity": @(engine->cache_capacity),
            @"cache_budget_bytes": @(engine->cache_budget), @"cached_estimated_bytes": @(engine->cached_bytes()),
            @"build_wall_seconds": @(engine->build_seconds), @"input_copy_wall_seconds": @(engine->copy_seconds),
            @"run_readback_wall_seconds": @(engine->run_readback_seconds),
            @"input_bytes": @(engine->input_bytes), @"output_bytes": @(engine->output_bytes), @"shape_calls": engine->shape_calls};
        NSData *data = [NSJSONSerialization dataWithJSONObject:info options:0 error:nil];
        static thread_local std::string encoded;
        encoded.assign(static_cast<const char *>(data.bytes), data.length);
        return encoded.c_str();
    }
}

extern "C" const char *jsr_graph_device_info() {
    @autoreleasepool {
        id<MTLDevice> device = MTLCreateSystemDefaultDevice();
        NSDictionary *info = @{@"device": device.name, @"unified_memory": @(device.hasUnifiedMemory),
            @"recommended_working_set_bytes": @(device.recommendedMaxWorkingSetSize),
            @"allocated_bytes": @(device.currentAllocatedSize), @"max_buffer_bytes": @(device.maxBufferLength)};
        NSData *data = [NSJSONSerialization dataWithJSONObject:info options:0 error:nil];
        static thread_local std::string encoded;
        encoded.assign(static_cast<const char *>(data.bytes), data.length);
        return encoded.c_str();
    }
}

#include "fusion_bridge.inc"

#pragma once

// Hard-coded UCAPI ABI constants and function pointer types.
//
// Values are copied from $VCS_HOME/linux64/include/covdb_user.h
// (X-2025.06-SP1).  The functions are resolved with dlsym at runtime so the
// binary does not bind to a specific VCS installation at build time.

namespace xcov {
namespace ucapi {

using Handle = void*;
using ErrorCallback = void (*)(Handle err, void* data);

// covdbObjTypesT
constexpr int kNullHandle = 1;
constexpr int kInternal = 2;
constexpr int kDesignObj = 3;
constexpr int kIterator = 4;
constexpr int kContainer = 5;
constexpr int kMetricObj = 6;
constexpr int kSourceInstance = 7;
constexpr int kSourceDefinition = 8;
constexpr int kBlock = 9;
constexpr int kIntegerValue = 10;
constexpr int kScalarValue = 11;
constexpr int kVectorValue = 12;
constexpr int kIntervalValue = 13;
constexpr int kBDDValue = 14;
constexpr int kCrossObj = 15;
constexpr int kSequence = 16;
constexpr int kAnnotation = 17;
constexpr int kTestObj = 18;
constexpr int kTestName = 19;
constexpr int kInterval = 20;
constexpr int kExcludeFile = 21;
constexpr int kHierFile = 22;
constexpr int kEditFile = 23;
constexpr int kBDD = 24;
constexpr int kErrorObj = 25;
constexpr int kTable = 26;
constexpr int kValueSet = 27;
constexpr int kSBNRange = 28;
constexpr int kTestInfo = 29;
constexpr int kUnionMergedDesign = 30;
constexpr int kSdcPath = 31;
constexpr int kLastObjEntry = 32;

// covdb1To1RelationsT
constexpr int kIdentity = 100;
constexpr int kParent = 101;
constexpr int kDefinition = 102;

// covdb1ToManyRelationsT
constexpr int kObjects = 200;
constexpr int kMetrics = 201;
constexpr int kInstances = 202;
constexpr int kDefinitions = 203;
constexpr int kAvailableTests = 205;

// covdbPropertiesT
constexpr int kName = 0;
constexpr int kFullName = 1;
constexpr int kFileName = 2;
constexpr int kLineNo = 3;
constexpr int kCoverable = 7;
constexpr int kDeepCoverable = 8;
constexpr int kValue = 9;
constexpr int kType = 11;
constexpr int kTypeStr = 12;
constexpr int kCovStatus = 13;
constexpr int kCovCount = 14;
constexpr int kCovered = 17;
constexpr int kDeepCovered = 18;
constexpr int kExcl = 34;
constexpr int kScopeName = 42;
constexpr int kChecksum = 48;

// covdbStatusT bits
constexpr int kStatusCovered = 8;
constexpr int kStatusExcludedAtReportTime = 64;

// AssertionType
constexpr int kAssertionTypeAssert = 0;
constexpr int kAssertionTypeCoverProperty = 1;
constexpr int kAssertionTypeCoverSequence = 2;

// Opaque function pointer signatures.
using FnLoad = Handle (*)(int what, Handle design, const char* logical_fname);
using FnLoadMerge = Handle (*)(int what, Handle dst, const char* logical_fname);
using FnUnload = int (*)(Handle design_or_test);
using FnIterate = Handle (*)(Handle obj, int relation);
using FnScan = Handle (*)(Handle iterator);
using FnRelease = void (*)(Handle obj);
using FnMakePersistent = Handle (*)(Handle obj);
using FnGet = int (*)(Handle obj, Handle region, Handle test, int property);
using FnGetStr = char* (*)(Handle obj, int property);
using FnGetQualifiedHandle = Handle (*)(Handle obj, Handle prop, int relation);
using FnQualifiedIterate = Handle (*)(Handle obj, Handle prop, int relation);
using FnGetAssertType = int (*)(Handle assert_hdl);
using FnSet = int (*)(Handle obj, Handle region, Handle test, int property, int value);
using FnSetAnnotation = int (*)(Handle obj, const char* key, const char* value);
using FnGetAnnotation = char* (*)(Handle obj, const char* key);
using FnSetDurable = int (*)(Handle region, Handle test, Handle obj, int value);
using FnIsDurable = int (*)(Handle region, Handle test, Handle obj);
using FnSaveExcludeFile = int (*)(Handle design_or_test, const char* fname, const char* mode);
using FnLoadExcludeFile = int (*)(Handle design_or_test, const char* fname);
using FnUnloadExclusion = int (*)(Handle design);
using FnSetErrorCallback = int (*)(ErrorCallback fn, void* data);
using FnConfigure = void (*)(int item, const char* value);
using FnVersion = const char* (*)(void);
using FnGetIntegerAnnotation = int (*)(Handle obj, const char* key);
using FnIsMetric = int (*)(Handle metric);

} // namespace ucapi
} // namespace xcov

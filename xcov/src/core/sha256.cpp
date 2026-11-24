#include "core/sha256.h"

#include <openssl/sha.h>

#include <cstdio>

namespace xcov {

std::string sha256_hex(const std::string& data) {
    unsigned char digest[SHA256_DIGEST_LENGTH];
    SHA256_CTX context;
    SHA256_Init(&context);
    SHA256_Update(&context, data.data(), data.size());
    SHA256_Final(digest, &context);
    static const char* kHex = "0123456789abcdef";
    std::string out;
    out.reserve(SHA256_DIGEST_LENGTH * 2);
    for (unsigned char byte : digest) {
        out.push_back(kHex[byte >> 4]);
        out.push_back(kHex[byte & 0x0f]);
    }
    return out;
}

} // namespace xcov

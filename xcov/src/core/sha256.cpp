#include "core/sha256.h"

#include "core/errors.h"

#include <openssl/sha.h>

#include <cstdio>
#include <fstream>

namespace xcov {

namespace {

std::string hex_encode(const unsigned char* digest) {
    static const char* kHex = "0123456789abcdef";
    std::string out;
    out.reserve(SHA256_DIGEST_LENGTH * 2);
    for (int index = 0; index < SHA256_DIGEST_LENGTH; ++index) {
        out.push_back(kHex[digest[index] >> 4]);
        out.push_back(kHex[digest[index] & 0x0f]);
    }
    return out;
}

std::string raw_encode(const unsigned char* digest) {
    return std::string(reinterpret_cast<const char*>(digest),
                       SHA256_DIGEST_LENGTH);
}

} // namespace

std::string sha256_hex(const std::string& data) {
    unsigned char digest[SHA256_DIGEST_LENGTH];
    SHA256_CTX context;
    SHA256_Init(&context);
    SHA256_Update(&context, data.data(), data.size());
    SHA256_Final(digest, &context);
    return hex_encode(digest);
}

std::string sha256_raw(const std::string& data) {
    unsigned char digest[SHA256_DIGEST_LENGTH];
    SHA256_CTX context;
    SHA256_Init(&context);
    SHA256_Update(&context, data.data(), data.size());
    SHA256_Final(digest, &context);
    return raw_encode(digest);
}

std::string sha256_file_raw(const std::string& path) {
    std::ifstream input(path, std::ios::binary);
    if (!input) {
        throw Error("IO_ERROR", "cannot open file for hashing", {{"path", path}});
    }
    SHA256_CTX context;
    SHA256_Init(&context);
    std::string buffer(1024 * 1024, '\0');
    while (input) {
        input.read(&buffer[0], static_cast<std::streamsize>(buffer.size()));
        const std::streamsize got = input.gcount();
        if (got > 0) {
            SHA256_Update(&context, buffer.data(),
                          static_cast<std::size_t>(got));
        }
    }
    if (input.bad()) {
        throw Error("IO_ERROR", "error while hashing file", {{"path", path}});
    }
    unsigned char digest[SHA256_DIGEST_LENGTH];
    SHA256_Final(digest, &context);
    return raw_encode(digest);
}

} // namespace xcov

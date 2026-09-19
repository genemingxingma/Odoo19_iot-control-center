#pragma once
#include <algorithm>
#include <cstdint>
#include <string>
#include <type_traits>
using std::min;
class String : public std::string {
public:
    using std::string::string;
    String() = default;
    String(const std::string& value) : std::string(value) {}
    template<class T, typename std::enable_if<std::is_arithmetic<T>::value, int>::type = 0>
    explicit String(T value) : std::string(std::to_string(value)) {}
    void replace(const char* before, const char* after) {
        size_t offset = 0;
        while ((offset = find(before, offset)) != npos) {
            std::string::replace(offset, std::char_traits<char>::length(before), after);
            offset += std::char_traits<char>::length(after);
        }
    }
};
class HardwareSerial {
public:
    std::string output;
    int availableForWrite() const { return 128; }
    size_t write(const uint8_t* bytes, size_t count) { output.append(reinterpret_cast<const char*>(bytes), count); return count; }
};
